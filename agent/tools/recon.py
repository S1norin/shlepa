#!/usr/bin/env python3
"""Deterministic reconnaissance for live targets (zero dependencies).

Four fixed stages, always run in this order:
  1. ports        top-100 port scan (threaded sockets)
  2. http         probe of the target URL: status, headers, title,
                  content-type, TLS certificate
  3. fingerprint  server / x-powered-by / generator meta /
                  JS library and framework signatures
  4. endpoints    BFS crawl (depth <= 2) + small bundled path wordlist

Contracts (do not weaken; the agent consumes this JSON as-is):
  * fail-safe: every stage emits its section even on error; a failed
    stage never aborts the run
  * hard total time budget: DEFAULT_TIMEOUT seconds (--timeout override),
    with per-stage and per-probe sub-timeouts
  * deterministic output: fixed section order, sorted lists, no wall-clock
    timestamps anywhere except the "timing" section
  * single JSON object on stdout, <= 3 KB (hard safety-net trim)

Usage:
    python3 tools/recon.py <url-or-host> [--timeout SECONDS]

<url-or-host> is a full URL (http(s)://host[:port][/path]) or a bare
host / host:port (probed with http by default, https when the port is 443).
"""

import argparse
import concurrent.futures
import json
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_TIMEOUT = 90.0
MAX_OUTPUT_BYTES = 3000
PORT_TIMEOUT = 0.2
PORT_WORKERS = 50
PORTS_CAP = 25
HTTP_TIMEOUT = 2.5
BODY_READ_CAP = 150_000
CRAWL_DEPTH = 2
CRAWL_MAX_PAGES = 8
CRAWL_WORKERS = 12
INTERESTING_CAP = 20
LINKS_CAP = 20
PROBE_WORKERS = 40
PROBE_TIMEOUT = 2.0
PROBE_TOTAL_CAP = 120
HEADER_NAMES = (
    "server",
    "x-powered-by",
    "x-aspnet-version",
    "content-type",
    "set-cookie",
    "www-authenticate",
    "allow",
)
USER_AGENT = "Mozilla/5.0 (compatible; shlepa-recon/1.0)"

#: Curated top-100 service ports (nmap "top 100" order), scanned first.
TOP100_PORTS = (
    21, 22, 23, 25, 53, 80, 81, 82, 88, 110, 111, 135, 139, 143, 161, 389,
    443, 445, 465, 512, 514, 515, 543, 554, 563, 587, 631, 636, 749, 777,
    873, 880, 888, 892, 992, 993, 995, 999, 1024, 1111, 1194, 1220, 1337,
    1433, 1521, 1556, 1645, 1723, 1755, 1812, 2000, 2001, 2049, 2082, 2083,
    2086, 2087, 2095, 2096, 2121, 2222, 2375, 2376, 2381, 2382, 2383, 2444,
    2556, 3000, 3001, 3128, 3306, 3389, 3690, 4040, 4443, 4444, 4567, 4899,
    4900, 5000, 5001, 5050, 5060, 5080, 5190, 5222, 5353, 5432, 5443, 5555,
    5672, 5683, 5900, 5984, 5988, 5989, 5990, 6000, 6001, 6009, 6112, 6222,
    6379, 6443, 6446, 6447, 6543, 6554, 6660, 6667, 6722, 6789, 6881, 6969,
    7000, 7001, 7002, 7077, 7100, 7183, 7443, 7474, 7475, 7476, 8000, 8008,
    8009, 8014, 8042, 8045, 8080, 8081, 8082, 8083, 8085, 8086, 8087, 8088,
    8089, 8090, 8118, 8180, 8181, 8222, 8300, 8333, 8443, 8500, 8649, 8880,
    8883, 8888, 8983, 9000, 9001, 9009, 9042, 9050, 9072, 9090, 9091, 9100,
    9117, 9200, 9207, 9300, 9312, 9418, 9443, 9593, 9626, 9999, 10000,
    10001, 10250, 11211, 11311, 12345, 15672, 16384, 18080, 19350, 1978,
    20000, 20005, 27017, 32768, 33333, 33899, 49152, 49153, 49155, 49163,
    49175, 49400, 50000, 54321, 55555, 59150,
)

PORT_SERVICES = {
    21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns", 80: "http",
    81: "http-alt", 110: "pop3", 111: "rpcbind", 135: "msrpc",
    139: "netbios", 143: "imap", 161: "snmp", 389: "ldap", 443: "https",
    445: "smb", 465: "smtps", 587: "submission", 631: "ipp", 636: "ldaps",
    873: "rsync", 993: "imaps", 995: "pop3s", 1433: "mssql",
    1521: "oracle", 1755: "rtsp", 2049: "nfs", 2375: "docker-api",
    2376: "docker-api-tls", 3000: "http", 3128: "http-proxy",
    3306: "mysql", 3389: "rdp", 4443: "https", 5000: "http",
    5432: "postgresql", 5443: "https", 5672: "amqp", 5900: "vnc",
    6379: "redis", 6443: "k8s-api", 7000: "http", 8000: "http",
    8080: "http", 8081: "http", 8443: "https", 8888: "http",
    9000: "http", 9090: "http", 9200: "elasticsearch",
    11211: "memcached", 15672: "rabbitmq-mgmt", 27017: "mongodb",
}

#: Small bundled path wordlist (deliberately modest: the crawl covers the
#: rest; the wordlist covers classic high-value paths).
WORDLIST = (
    "/admin", "/admin/", "/login", "/login.php", "/admin.php",
    "/wp-login.php", "/wp-admin/", "/wp-json/", "/xmlrpc.php",
    "/api", "/api/", "/api/v1", "/api/v2", "/api/users", "/api/admin",
    "/api/auth", "/api/health", "/api/status", "/api/docs",
    "/health", "/healthz", "/status", "/metrics", "/debug", "/debug/pprof/",
    "/actuator", "/actuator/health", "/actuator/env", "/swagger-ui.html",
    "/openapi.json", "/api-docs", "/docs", "/graphql", "/search", "/users",
    "/profile", "/dashboard", "/panel", "/console", "/manager",
    "/phpmyadmin/", "/solr/", "/jenkins/", "/grafana/", "/kibana/",
    "/nacos/", "/elasticsearch/", "/prometheus/", "/internal/", "/hidden/",
    "/secret", "/secret.txt", "/flag", "/flag.txt", "/flag.php", "/hint",
    "/source", "/source.txt", "/backup", "/backup.zip", "/db.sql",
    "/dump.sql", "/uploads/", "/files/", "/download/", "/temp/", "/tmp/",
    "/favicon.ico", "/robots.txt", "/sitemap.xml", "/feed", "/rss",
    "/web.config", "/crossdomain.xml", "/.env", "/.git/", "/.git/config",
    "/.git/HEAD", "/.htaccess", "/.aws/credentials", "/.ssh/id_rsa",
    "/config", "/config.php", "/config.json", "/settings.json",
    "/package.json", "/composer.json", "/requirements.txt", "/Dockerfile",
    "/docker-compose.yml", "/phpinfo.php", "/info.php", "/server-status",
    "/server-info", "/test", "/index.php", "/main", "/about", "/contact",
    "/error", "/exception", "/traceback",
)

JS_SIGNATURES = {
    "jquery": re.compile(r"jquery[.-]?\d"),
    "react": re.compile(r"react[-.]|__NEXT_DATA__|_next/"),
    "vue": re.compile(r"vue[.-]|\bdata-v-[0-9a-f]{8}"),
    "angular": re.compile(r"ng-version=|angular\.\d|__ng"),
    "bootstrap": re.compile(r"bootstrap[.-]?\d"),
    "moment": re.compile(r"moment[.-]?\d"),
    "lodash": re.compile(r"lodash[.-]?\d"),
}
FRAMEWORK_SIGNATURES = {
    "wordpress": re.compile(r"wp-content|wp-includes|wp-json"),
    "django": re.compile(r"csrfmiddlewaretoken|powered by django"),
    "laravel": re.compile(r"laravel|XSRF-TOKEN"),
    "php": re.compile(r"PHPSESSID"),
    "jsp": re.compile(r"JSESSIONID|jsessionid"),
    "spring": re.compile(r"spring[-_]|X-Application-Context"),
    "aspnet": re.compile(r"__VIEWSTATE|aspx"),
    "nextjs": re.compile(r"_next/static"),
}

ANCHOR_RE = re.compile(r"<(?:a|area)\s[^>]*href=[\"']([^\"'\s>]+)[\"']", re.I)
JS_PATH_RE = re.compile(r"""["'](\/[A-Za-z0-9_\-./%?=&]{2,100})["']""")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
GENERATOR_RE = re.compile(r"<meta[^>]*name=[\"']?generator[\"']?[^>]*>", re.I)
CONTENT_ATTR_RE = re.compile(r"content=[\"']([^\"']+)[\"']", re.I)
WHITESPACE_RE = re.compile(r"\s+")


class Budget:
    """Monotonic total-time budget shared by all stages."""

    def __init__(self, total: float) -> None:
        self.total = total
        self.start = time.monotonic()

    def remaining(self) -> float:
        return max(0.0, self.total - (time.monotonic() - self.start))

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def take(self, cap: float) -> float:
        """Reserve up to `cap` seconds; 0.0 when the budget is spent."""
        left = self.remaining()
        return min(cap, left) if left > 0.0 else 0.0


def cap_text(value, limit: int):
    """Char-cap a field; None stays None (never crashes on odd input)."""
    if value is None:
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def safe_headers(headers) -> dict:
    """Selected response headers, lower-cased keys, per-value char cap."""
    lower = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    return {
        name: cap_text(lower[name], 120)
        for name in HEADER_NAMES
        if name in lower
    }


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_cert(host: str, port: int, timeout: float):
    """TLS certificate facts, or None. Works with self-signed certs."""
    if timeout <= 0.0:
        return None
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with _ssl_context().wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
    except (OSError, ssl.SSLError):
        return None
    subject = dict(x[0] for x in cert.get("subject", ()))
    issuer = dict(x[0] for x in cert.get("issuer", ()))
    sans = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
    return {
        "subject": cap_text(subject.get("commonName"), 120),
        "issuer": cap_text(issuer.get("commonName"), 120),
        "sans": sorted(sans)[:5],
        "not_after": cert.get("notAfter"),
    }


def http_get(url: str, timeout: float):
    """GET with redirects followed; returns (status, headers, body, final_url).

    HTTP 4xx/5xx responses are returned, not raised (they are data).
    """
    context = _ssl_context() if url.lower().startswith("https") else None
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            return (
                resp.status,
                dict(resp.headers),
                resp.read(BODY_READ_CAP),
                resp.geturl(),
            )
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers or {}), err.read(BODY_READ_CAP), err.geturl()


def stage_ports(host: str, target_port, budget: Budget) -> dict:
    """Stage 1: top-100 port scan (threaded sockets).

    The target URL's own port is always probed and always shown (it may be
    outside the top-100 list, e.g. a fixture on an ephemeral port).
    """
    timeout = min(PORT_TIMEOUT, budget.take(20.0))
    if timeout <= 0.0:
        return {"status": "skipped", "open": [], "scanned": 0,
                "note": "time budget exhausted"}
    ports = list(TOP100_PORTS)
    if target_port is not None and target_port not in ports:
        ports.append(target_port)
    open_ports = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=PORT_WORKERS) as pool:
        futures = {
            port: pool.submit(_probe_port, host, port, timeout)
            for port in ports
        }
        for port in sorted(futures):
            try:
                if futures[port].result(timeout=timeout + 1.0):
                    open_ports.add(port)
            except concurrent.futures.TimeoutError:
                pass
    open_sorted = sorted(open_ports)
    shown = [
        p
        for p in open_sorted
        if p != target_port
    ][:PORTS_CAP]
    if target_port in open_ports:
        idx = 0
        while idx < len(shown) and shown[idx] < target_port:
            idx += 1
        shown.insert(idx, target_port)
    return {
        "status": "ok",
        "open": [
            {"port": p, "service": PORT_SERVICES.get(p)} for p in shown
        ],
        "scanned": len(futures),
        "note": (
            f"showing first {len(shown)} of {len(open_sorted)} open ports"
            if len(open_sorted) > len(shown)
            else None
        ),
    }


def _probe_port(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def stage_http(url: str, host: str, port: int, budget: Budget, ctx: dict) -> dict:
    """Stage 2: probe the target URL (status, headers, title, TLS cert)."""
    timeout = budget.take(10.0)
    if timeout <= 0.0:
        return {"status": "skipped", "note": "time budget exhausted"}
    section = {"status": "ok", "url": url}
    try:
        status, headers, body, final_url = http_get(url, timeout)
    except (OSError, ssl.SSLError, urllib.error.URLError) as err:
        section["status"] = "error"
        section["error"] = cap_text(f"{type(err).__name__}: {err}", 160)
        return section
    body_text = body.decode("utf-8", "replace")
    ctx["body"] = body_text
    title = TITLE_RE.search(body_text)
    section.update(
        {
            "url": cap_text(final_url, 200),
            "http_status": status,
            "headers": safe_headers(headers),
            "title": cap_text(
                WHITESPACE_RE.sub(" ", title.group(1)).strip(), 160
            )
            if title
            else None,
        }
    )
    if url.lower().startswith("https"):
        section["tls"] = fetch_cert(host, port, min(5.0, budget.take(5.0)))
    return section


def stage_fingerprint(http_section: dict, ctx: dict) -> dict:
    """Stage 3: tech fingerprint over the stage-2 response (no new I/O)."""
    headers = http_section.get("headers") or {}
    section = {
        "server": cap_text(headers.get("server"), 120),
        "x_powered_by": cap_text(headers.get("x-powered-by"), 120),
        "generator": None,
        "js": [],
        "frameworks": [],
    }
    body = ctx.get("body")
    if body:
        meta = GENERATOR_RE.search(body)
        if meta:
            content = CONTENT_ATTR_RE.search(meta.group(0))
            if content:
                section["generator"] = cap_text(content.group(1), 120)
        section["js"] = sorted(
            name for name, rx in JS_SIGNATURES.items() if rx.search(body)
        )
        section["frameworks"] = sorted(
            name for name, rx in FRAMEWORK_SIGNATURES.items() if rx.search(body)
        )
    return section


def _norm_link(base: str, raw: str):
    """Resolve a link against base; keep same-origin, return the path part."""
    raw = raw.strip()
    if not raw or raw.startswith(
        ("mailto:", "tel:", "javascript:", "data:", "#", "//")
    ):
        return None
    candidate = urllib.parse.urljoin(base, raw)
    parts = urllib.parse.urlsplit(candidate)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    base_netloc = urllib.parse.urlsplit(base).netloc
    if parts.netloc != base_netloc:
        return None
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return path


def _crawl_page(url: str):
    """GET one page; returns (url, status, title, is_html, extracted links)."""
    try:
        status, headers, body, final_url = http_get(url, HTTP_TIMEOUT)
    except (OSError, ssl.SSLError, urllib.error.URLError):
        return url, None, None, None, []
    body_text = body.decode("utf-8", "replace")
    ctype = str(headers.get("Content-Type", headers.get("content-type", "")))
    title = TITLE_RE.search(body_text)
    title = cap_text(WHITESPACE_RE.sub(" ", title.group(1)).strip(), 120) if title else None
    links = [m.group(1) for m in ANCHOR_RE.finditer(body_text)]
    links += [m.group(1) for m in JS_PATH_RE.finditer(body_text)]
    return final_url or url, status, title, "text/html" in ctype, links


def stage_endpoints(url: str, host: str, port: int, budget: Budget) -> dict:
    """Stage 4: BFS crawl (depth <= 2) + small path wordlist brute."""
    scheme = urllib.parse.urlsplit(url).scheme
    netloc = f"{host}:{port}" if port else host
    origin = f"{scheme}://{netloc}"
    section = {"status": "ok", "pages": [], "interesting": [], "links": []}
    if budget.expired():
        section["status"] = "skipped"
        section["note"] = "time budget exhausted"
        return section

    # -- BFS crawl ---------------------------------------------------------
    start_parts = urllib.parse.urlsplit(url)
    start_path = start_parts.path or "/"
    if start_parts.query:
        start_path += "?" + start_parts.query
    pages = {}
    links = set()
    seen = {start_path}
    frontier = [(origin + start_path, 0)]
    while frontier and len(pages) < CRAWL_MAX_PAGES and not budget.expired():
        next_frontier = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=CRAWL_WORKERS
        ) as pool:
            futures = {u: pool.submit(_crawl_page, u) for u, _ in frontier}
            for page_url, depth in frontier:
                if len(pages) >= CRAWL_MAX_PAGES:
                    break
                try:
                    _, status, title, is_html, found_links = (
                        futures[page_url].result(timeout=HTTP_TIMEOUT + 1.0)
                    )
                except concurrent.futures.TimeoutError:
                    status, title, is_html, found_links = None, None, None, []
                rel = urllib.parse.urlsplit(page_url).path or "/"
                if status is None:
                    pages[rel] = {"path": rel, "status": None}
                    continue
                entry = {"path": rel, "status": status}
                if title:
                    entry["title"] = title
                pages[rel] = entry
                if not is_html or depth >= CRAWL_DEPTH:
                    continue
                for raw in found_links:
                    resolved = _norm_link(page_url, raw)
                    if resolved is None:
                        continue
                    links.add(resolved)
                    crawl_path = resolved.split("?")[0] or "/"
                    if crawl_path in seen:
                        continue
                    seen.add(crawl_path)
                    next_frontier.append((origin + crawl_path, depth + 1))
        frontier = next_frontier[:CRAWL_MAX_PAGES]
    section["pages"] = [pages[k] for k in sorted(pages)]
    section["links"] = sorted(links)[:LINKS_CAP]

    # -- path wordlist brute against the origin root ------------------------
    interesting = []
    if not budget.expired():
        baseline = _probe_path(origin + "/shlepa-recon-baseline-404", budget)
        candidates = sorted(
            set(WORDLIST) | {link.split("?")[0] for link in links}
        )[:PROBE_TOTAL_CAP]
        with concurrent.futures.ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
            futures = {
                path: pool.submit(_probe_path, origin + path, budget)
                for path in candidates
                if not budget.expired()
            }
            for path in sorted(futures):
                probe = futures[path].result()
                if probe is None:
                    continue
                status, length = probe
                if baseline is None:
                    if status != 404:
                        interesting.append({"path": path, "status": status})
                    continue
                base_status, base_len = baseline
                # A hit: status differs from the baseline 404, or the status
                # matches but the length does not (soft-404 detection).
                if status != base_status or abs(length - base_len) > 64:
                    interesting.append({"path": path, "status": status})
    section["interesting"] = interesting[:INTERESTING_CAP]
    if len(interesting) > INTERESTING_CAP:
        section["note"] = f"showing first {INTERESTING_CAP} interesting paths"
    return section


def _probe_path(url: str, budget: Budget):
    """GET one candidate path; returns (status, body_len) or None."""
    timeout = budget.take(2.0)
    if timeout <= 0.0:
        return None
    try:
        status, _, body, _ = http_get(url, min(PROBE_TIMEOUT, timeout))
        return status, len(body)
    except (OSError, ssl.SSLError, urllib.error.URLError):
        return None


def _trim_to_budget(result: dict) -> None:
    """Drop list entries (biggest sections first) until output fits the cap."""

    def size() -> int:
        return len(json.dumps(result, separators=(",", ":")).encode("utf-8"))

    lists = (
        result["endpoints"]["links"],
        result["endpoints"]["pages"],
        result["endpoints"]["interesting"],
        result["ports"]["open"],
        result["fingerprint"]["js"],
        result["fingerprint"]["frameworks"],
    )
    for lst in lists:
        while size() > MAX_OUTPUT_BYTES and lst:
            lst.pop()


def run_recon(target: str, timeout: float) -> dict:
    url, host, port = _parse_target(target)
    budget = Budget(timeout)
    ctx: dict = {}
    result = {"target": cap_text(url, 200), "host": host}
    timing: dict = {}

    stage_specs = (
        ("ports", lambda: stage_ports(host, port, budget)),
        ("http", lambda: stage_http(url, host, port, budget, ctx)),
        ("endpoints", lambda: stage_endpoints(url, host, port, budget)),
    )
    for name, fn in stage_specs:
        started = time.monotonic()
        try:
            section = fn()
        except Exception as err:  # fail-safe: a stage never aborts the run
            section = {
                "status": "error",
                "error": cap_text(f"{type(err).__name__}: {err}", 160),
            }
        result[name] = section
        timing[name + "_sec"] = round(time.monotonic() - started, 2)
    # Fingerprint is pure computation over the http stage; always emitted.
    try:
        result["fingerprint"] = stage_fingerprint(result.get("http") or {}, ctx)
    except Exception as err:  # fail-safe
        result["fingerprint"] = {
            "status": "error",
            "error": cap_text(f"{type(err).__name__}: {err}", 160),
        }
    timing["fingerprint_sec"] = 0.0
    timing["total_sec"] = round(budget.total - budget.remaining(), 2)
    if budget.expired():
        result["note"] = "time budget exhausted; later stages may be truncated"
    result["timing"] = timing
    _trim_to_budget(result)
    return result


def _parse_target(target: str):
    """Accept a URL or a bare host[:port]; return (url, host, port|None)."""
    target = target.strip()
    if "://" in target:
        parts = urllib.parse.urlsplit(target)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"unsupported target URL: {target!r}")
        host = parts.hostname
        port = parts.port
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        return f"{parts.scheme}://{parts.netloc}{path}", host, port
    host = target
    port = None
    if target.count(":") == 1:
        host, port_text = target.split(":", 1)
        port = int(port_text)  # ValueError -> usage error in main()
    scheme = "https" if port == 443 else "http"
    netloc = f"{host}:{port}" if port else host
    return f"{scheme}://{netloc}/", host, port


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic 4-stage reconnaissance; prints one JSON object (<=3KB)."
        )
    )
    parser.add_argument("target", help="URL (http/https) or host[:port]")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"hard total time budget in seconds (default {DEFAULT_TIMEOUT:g})",
    )
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        print("error: --timeout must be positive", file=sys.stderr)
        return 2
    try:
        result = run_recon(args.target, args.timeout)
    except (ValueError, OSError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
