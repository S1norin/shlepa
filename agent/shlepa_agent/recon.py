"""Deterministic attack-surface recon engine (stdlib only, no LLM).

Engine module behind the CLI script ``tools/recon.py`` (thin wrapper) and,
later, the registered ``recon`` tool. Maps a surface; never claims a
vulnerability.

Public entry functions (one per mode):
  - ``recon_web(url)``    network map of a live web target
  - ``recon_code(path)``  code-surface map of a source tree
  - ``recon_data(path)``  data/log-surface map of an evidence dir
plus ``render`` (8KB-capped JSON serialization) and ``err_note`` (compact
exception notes).

Contract:
  - compact flat JSON dict, hard total cap 8192 bytes when serialized via
    ``render`` (per-field caps, progressive list truncation as a backstop)
  - deterministic: fixed probe lists and order; only stats.elapsed_s varies
  - fail-safe: a stage failure emits its section with an error note and
    never aborts the run
  - pure stdlib; no side effects on import

Design rules (see research/notes/recon-deterministic.md):
deterministic engine + LLM interpretation; signals, not verdicts.
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import os
import re
import socket
import ssl
import time
import urllib.parse
from collections import deque
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path

MAX_TOTAL = 8192          # hard cap on serialized output bytes
DEADLINE_S = 100.0        # internal wall budget for the crawl
MAX_REQUESTS = 150        # crawl + sensitive combined
MAX_BODY = 16384          # per-response body cap for parsing
BINARY_EXT = re.compile(
    r"\.(png|jpe?g|gif|ico|css|js|mjs|woff2?|ttf|eot|svg|mp4|webm|"
    r"zip|gz|tgz|pdf|bin|iso|docx?|xlsx?)$",
    re.I,
)

# ---------------------------------------------------------------------------
# fixed probe lists (deterministic)
# ---------------------------------------------------------------------------

PORTS = [
    21, 22, 23, 25, 53, 80, 81, 110, 111, 135, 139, 143, 161, 389, 443, 445,
    465, 587, 593, 636, 993, 995, 1080, 1433, 1521, 2049, 2181, 2222, 2375,
    3000, 3001, 3128, 3306, 3389, 4443, 4444, 4567, 5000, 5001, 5432, 5555,
    5601, 5672, 5900, 6379, 7001, 7443, 8000, 8080, 8081, 8082, 8085, 8086,
    8088, 8090, 8443, 8888, 9000, 9001, 9090, 9091, 9200, 9300, 9999,
    10000, 11211, 15672, 19000, 27017,
]

PORT_SERVICES = {
    21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns", 80: "http",
    81: "http", 110: "pop3", 111: "rpcbind", 135: "msrpc", 139: "netbios",
    143: "imap", 161: "snmp", 389: "ldap", 443: "https", 445: "smb",
    465: "smtps", 587: "smtp", 593: "http-rpc", 636: "ldaps", 993: "imaps",
    995: "pop3s", 1080: "socks", 1433: "mssql", 1521: "oracle", 2049: "nfs",
    2181: "zookeeper", 2222: "ssh", 2375: "docker", 3000: "http",
    3001: "http", 3128: "proxy", 3306: "mysql", 3389: "rdp", 4443: "https",
    4444: "https", 4567: "http", 5000: "http", 5001: "http", 5432: "postgres",
    5555: "vnc", 5601: "kibana", 5672: "amqp", 5900: "vnc", 6379: "redis",
    7001: "http", 7443: "https", 8000: "http", 8080: "http", 8081: "http",
    8082: "http", 8085: "http", 8086: "http", 8088: "http", 8090: "http",
    8443: "https", 8888: "http", 9000: "http", 9001: "http", 9090: "http",
    9091: "http", 9200: "elasticsearch", 9300: "elasticsearch", 9999: "http",
    10000: "http", 11211: "memcached", 15672: "rabbitmq-mgmt", 19000: "http",
    27017: "mongo",
}

VHOSTS = [
    "localhost", "admin", "internal", "hidden", "secret", "dev", "staging",
    "beta", "test", "old", "new", "portal", "shop", "blog", "wiki", "mail",
    "api", "app", "cdn", "db", "db1", "dc01", "corp", "local", "intranet",
    "private", "vault", "flag", "target", "127.0.0.1",
]

CRAWL_PATHS = [
    "/", "/login", "/signin", "/auth", "/logout", "/users", "/user",
    "/profile", "/register", "/signup", "/admin", "/console", "/dashboard",
    "/search", "/query", "/q", "/api", "/api/v1", "/v1", "/v2", "/graphql",
    "/ws", "/upload", "/download", "/files", "/export", "/import",
    "/health", "/healthz", "/status", "/info", "/debug", "/metrics", "/env",
    "/config", "/settings", "/docs", "/documentation", "/api-docs",
    "/rest", "/services", "/exec", "/run", "/shell", "/cmd", "/test",
    "/dev", "/internal", "/backup", "/home", "/about", "/contact", "/support",
    "/help", "/sitemap.xml", "/feed", "/wp-login.php", "/wp-admin/",
    "/wp-json/", "/xmlrpc.php", "/cgi-bin/", "/server-status", "/server-info",
    "/phpinfo.php", "/phpmyadmin/", "/trace", "/errors", "/logs",
    "/report", "/reports", "/analytics", "/jobs", "/tasks", "/webhooks",
    "/token", "/oauth", "/sso", "/saml", "/callback", "/account",
    "/password/reset", "/reset-password", "/forgot", "/activate",
]

SENSITIVE_PATHS = [
    "/robots.txt", "/sitemap.xml", "/.git/config", "/.git/HEAD", "/.env",
    "/.env.local", "/.svn/entries", "/web.config", "/package.json",
    "/composer.json", "/docker-compose.yml", "/config.yml", "/settings.py",
    "/id_rsa", "/backup.sql", "/db.sql", "/dump.sql", "/.htaccess",
    "/.htpasswd", "/server-status", "/server-info", "/actuator",
    "/actuator/health", "/actuator/env", "/swagger.json", "/openapi.json",
]

TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
FLAG_RE = re.compile(r"flag\{[^}\n]*\}")
HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,64}\b")
B64_RE = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b")
KEYVAL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=[^\s=]")

SKIP_DIRS = {
    "node_modules", ".git", "venv", ".venv", "__pycache__", "dist", "build",
    ".next", "target", ".idea", ".pytest_cache", "coverage", ".cache",
}

SINKS = [
    ("eval", re.compile(r"(?<![\w.])eval\s*\(")),
    ("exec", re.compile(r"(?<![\w.])exec\s*\(")),
    ("os.system", re.compile(r"os\.system\s*\(")),
    ("subprocess shell=True", re.compile(r"subprocess\.\w+\s*\([^)]*shell\s*=\s*True")),
    ("raw SQL f-string", re.compile(r"\.(execute|executemany)\s*\(\s*f['\"]")),
    ("SQL concat", re.compile(r"(?:sql|query)\s*=\s*f['\"]")),
    ("pickle loads", re.compile(r"pickle\.loads?\s*\(")),
    ("yaml unsafe load", re.compile(r"yaml\.load\s*\(")),
    ("weak crypto", re.compile(r"hashlib\.(md5|sha1)\s*\(")),
    ("hardcoded secret",
     re.compile(r"(?i)\b(?:password|passwd|api_?key|secret|token)\b\s*=\s*['\"][^'\"]{4,}['\"]")),
    ("render_template_string", re.compile(r"render_(?:template_)?string\s*\(")),
    ("php shell exec",
     re.compile(r"(?<![\w>])(?:system|shell_exec|passthru|popen|proc_open)\s*\(")),
    ("php eval/assert", re.compile(r"(?<![\w>])(?:eval|assert)\s*\(")),
    ("php mysql_query", re.compile(r"mysql_query\s*\(")),
    ("php unserialize", re.compile(r"(?<![\w>])unserialize\s*\(")),
    ("js child_process", re.compile(r"require\s*\(\s*['\"]child_process")),
]

ENTRY_POINTS = [
    ("FastAPI app", re.compile(r"FastAPI\(")),
    ("Flask app", re.compile(r"Flask\(")),
    ("route", re.compile(r"@(?:app|router)\.(?:route|get|post|put|delete|patch)\s*\(")),
    ("main()", re.compile(r"^def main\(")),
    ("app.run", re.compile(r"app\.run\s*\(")),
    ("php route", re.compile(r"Route::(?:get|post|put|delete|any)\s*\(")),
]


# ---------------------------------------------------------------------------
# output rendering with a hard size cap
# ---------------------------------------------------------------------------

def render(obj: dict) -> str:
    def dump() -> bytes:
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=True).encode()

    data = dump()
    if len(data) <= MAX_TOTAL:
        return data.decode()
    # backstop: halve the largest lists until it fits
    for key in ("endpoints", "errors", "files", "sinks", "sensitive",
                "vhosts", "interesting", "data_files", "needles"):
        if len(data) <= MAX_TOTAL:
            break
        value = obj.get(key)
        if isinstance(value, list) and len(value) > 1:
            obj[key] = value[: max(1, len(value) // 2)]
            data = dump()
    return data.decode()


def err_note(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:120]}"


# ---------------------------------------------------------------------------
# web mode
# ---------------------------------------------------------------------------

class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.forms: list[dict] = []
        self._form: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("a", "link") and a.get("href"):
            self.links.append(a["href"])
        elif tag == "script" and a.get("src"):
            self.links.append(a["src"])
        elif tag == "form":
            self._form = {
                "action": a.get("action", ""),
                "method": (a.get("method") or "get").lower(),
                "fields": [],
            }
            self.forms.append(self._form)
        elif tag in ("input", "textarea", "select") and self._form is not None:
            name = a.get("name")
            if name and len(self._form["fields"]) < 8:
                self._form["fields"].append(name)

    def handle_endtag(self, tag):
        if tag == "form":
            self._form = None


def _connect(scheme: str, host: str, port: int, host_header: str | None,
             timeout: float):
    if scheme == "https":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return HTTPSConnection(host, port, timeout=timeout, context=ctx,
                               server_hostname=host_header or host)
    return HTTPConnection(host, port, timeout=timeout)


def http_get(host: str, port: int, path: str, scheme: str,
             host_header: str | None, timeout: float = 4.0, follow: int = 3):
    """GET with manual redirect following.

    Returns (status, {lower_header: value}, body_bytes, final_path, redirects).
    """
    redirects = []
    cur_path = path
    for _ in range(follow + 1):
        headers = {}
        if host_header:
            headers["Host"] = host_header
        conn = _connect(scheme, host, port, host_header, timeout)
        try:
            conn.request("GET", cur_path, headers=headers)
            resp = conn.getresponse()
            body = resp.read(MAX_BODY)
            hdrs = {k.lower(): v for k, v in resp.getheaders()}
            loc = hdrs.get("location")
            if resp.status in (301, 302, 303, 307, 308) and loc:
                redirects.append(f"{resp.status} {loc[:80]}")
                sp = urllib.parse.urlsplit(loc)
                cur_path = sp.path or "/"
                if sp.query:
                    cur_path += "?" + sp.query
                continue
            return resp.status, hdrs, body, cur_path, redirects
        finally:
            conn.close()
    raise RuntimeError("too many redirects")


def _title(body: bytes) -> str | None:
    m = re.search(rb"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    if not m:
        return None
    text = m.group(1).decode("utf-8", "replace")[:60]
    return " ".join(text.split()) or None


def scan_ports(host: str, target_port: int, deadline: float) -> dict:
    open_ports: dict[int, str] = {}
    ports = sorted(set(PORTS + [target_port]))

    def probe(port: int) -> tuple[int, bool, str | None]:
        try:
            if time.monotonic() > deadline:
                return port, False, None
            s = socket.create_connection((host, port), timeout=0.15)
        except OSError:
            return port, False, None
        banner = None
        try:
            s.settimeout(0.5)
            try:
                chunk = s.recv(64)
            except OSError:
                chunk = b""
            if not chunk:
                try:
                    s.sendall(b"GET / HTTP/1.0\r\nHost: x\r\n\r\n")
                    s.settimeout(0.5)
                    chunk = s.recv(96)
                except OSError:
                    chunk = b""
            if chunk:
                raw = chunk.split(b"\r\n", 1)[0].split(b"\n", 1)[0]
                printable = "".join(
                    ch for ch in raw.decode("latin-1") if 32 <= ord(ch) < 127)
                banner = printable.strip()[:50] or None
        except OSError:
            pass
        finally:
            s.close()
        return port, True, banner

    with cf.ThreadPoolExecutor(16) as ex:
        for port, is_open, banner in ex.map(probe, ports):
            if not is_open:
                continue
            guess = PORT_SERVICES.get(port, "open")
            open_ports[port] = f"{guess} ({banner})" if banner else guess
    return {str(p): open_ports[p] for p in sorted(open_ports)}


def probe_endpoint(host: str, ip: str, port: int, scheme: str, path: str,
                   deadline: float) -> dict:
    remaining = max(0.5, min(4.0, deadline - time.monotonic()))
    status, hdrs, body, final_path, redirects = http_get(
        ip, port, path, scheme, host_header=host, timeout=remaining)
    ctype = (hdrs.get("content-type") or "").split(";")[0].strip().lower()
    entry: dict = {"path": path, "status": status}
    if ctype and ctype != "text/html":
        entry["type"] = ctype[:40]
    title = _title(body)
    if title:
        entry["title"] = title
    if ctype == "text/html":
        parser = _PageParser()
        try:
            parser.feed(body.decode("utf-8", "replace"))
        except Exception:
            pass
        if parser.forms:
            forms = []
            for form in parser.forms[:3]:
                f: dict = {}
                if form["action"]:
                    f["action"] = form["action"][:60]
                f["method"] = form["method"]
                if form["fields"]:
                    f["fields"] = form["fields"][:6]
                forms.append(f)
            entry["forms"] = forms
        if parser.links:
            entry["_links"] = parser.links[:20]
    query = path.split("?", 1)[1] if "?" in path else ""
    if query:
        params = []
        for kv in query.split("&")[:8]:
            name = kv.split("=", 1)[0]
            if name and name not in params:
                params.append(name)
        if params:
            entry["params"] = params
    if status >= 400:
        text = " ".join(body.decode("utf-8", "replace").split())[:160]
        entry["excerpt"] = text or None
    elif status == 200 and ctype in ("text/plain", "application/json") \
            and len(body) <= 256:
        # small plain bodies (robots.txt, .git/config, tiny JSON) are the
        # whole signal; include them
        text = " ".join(body.decode("utf-8", "replace").split())[:120]
        if text:
            entry["excerpt"] = text
    if redirects:
        entry["redirects"] = redirects[:3]
    return entry


def recon_web(url: str) -> dict:
    t0 = time.monotonic()
    deadline = t0 + DEADLINE_S
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme or "http"
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if scheme == "https" else 80)
    seed_path = parsed.path or "/"
    if parsed.query:
        seed_path += "?" + parsed.query
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        ip = host

    out: dict = {"url": url}
    requests = 0
    dropped = 0

    # stage 1: open ports
    if time.monotonic() < deadline - 15:
        try:
            out["ports_open"] = scan_ports(ip, port, deadline)
        except Exception as e:
            out["ports_open"] = {"error": err_note(e)}
    else:
        out["ports_open"] = {"error": "skipped (deadline)"}

    # stage 2: base http probe
    baseline = None
    base: dict = {}
    try:
        status, hdrs, body, final_path, redirects = http_get(
            ip, port, seed_path, scheme, host_header=None, timeout=5.0)
        requests += 1
        base = {"status": status, "final_path": final_path}
        for h in ("server", "x-powered-by", "www-authenticate"):
            if hdrs.get(h):
                base[h] = hdrs[h][:60]
        cookies = [c.split("=", 1)[0] for c in
                   (hdrs.get("set-cookie") or "").split(", ") if c]
        if cookies:
            base["cookies"] = cookies[:4]
        if scheme == "https":
            try:
                with socket.create_connection((ip, port), timeout=4) as raw:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    with ctx.wrap_socket(raw, server_hostname=host) as tls:
                        cert = tls.getpeercert()
                        sans = [tuple(x) for x in cert.get("subjectAltName", ())]
                        names = [v for k, v in sans if k == "DNS"]
                        if names:
                            base["tls_sans"] = names[:8]
            except OSError:
                pass
        ctype = (hdrs.get("content-type") or "").split(";")[0].strip()
        if ctype:
            base["content_type"] = ctype[:40]
        title = _title(body)
        if title:
            base["title"] = title
        if redirects:
            base["redirects"] = redirects[:3]
        baseline = (status, hdrs.get("server", ""), title or "",
                    hashlib.sha256(body[:2048]).hexdigest()[:8])
    except Exception as e:
        base["error"] = err_note(e)
    out["http"] = base

    # stage 3: vhost discovery (Host header probing against the IP)
    vhosts = []
    if baseline and time.monotonic() < deadline - 30:
        candidates = [h for h in VHOSTS if h.lower() != host.lower()]
        found: dict[str, dict] = {}

        def vprobe(name: str) -> tuple[str, dict | None]:
            if time.monotonic() > deadline:
                return name, None
            try:
                status, hdrs, body, _, _ = http_get(
                    ip, port, "/", scheme, host_header=name, timeout=3.0)
            except Exception:
                return name, None
            sig = (status, hdrs.get("server", ""), _title(body) or "",
                   hashlib.sha256(body[:2048]).hexdigest()[:8])
            if sig != baseline:
                entry: dict = {"host": name, "status": status}
                if hdrs.get("server"):
                    entry["server"] = hdrs["server"][:40]
                title = _title(body)
                if title:
                    entry["title"] = title
                entry["body_hash"] = sig[3]
                return name, entry
            return name, None

        with cf.ThreadPoolExecutor(6) as ex:
            for name, entry in ex.map(vprobe, candidates):
                if entry:
                    found[name] = entry
        vhosts = [found[name] for name in sorted(found)]
    out["vhosts"] = vhosts

    # stage 4: endpoint inventory (wordlist seeds + BFS crawl)
    results: dict[str, dict] = {}
    new_paths: list[str] = []

    def probe(path: str) -> dict:
        try:
            entry = probe_endpoint(host, ip, port, scheme, path, deadline)
            return entry
        except Exception as e:
            return {"path": path, "error": err_note(e)}

    if baseline and time.monotonic() < deadline - 15:
        frontier = [seed_path] + [p for p in CRAWL_PATHS if p != seed_path]
        for depth in range(3):
            if not frontier:
                break
            batch = [p for p in frontier if p not in results]
            budget = MAX_REQUESTS - len(results)
            batch = batch[: max(0, budget)]
            if not batch:
                break
            with cf.ThreadPoolExecutor(8) as ex:
                futs = {ex.submit(probe, p): p for p in batch}
                for fut in cf.as_completed(futs):
                    p = futs[fut]
                    try:
                        results[p] = fut.result()
                    except Exception as e:
                        results[p] = {"path": p, "error": err_note(e)}
                    requests += 1
            if depth < 2:
                nxt: set[str] = set()
                for p, entry in results.items():
                    for link in entry.pop("_links", []) or []:
                        full = urllib.parse.urljoin(
                            f"{scheme}://{host}:{port}", link)
                        sp = urllib.parse.urlsplit(full)
                        if sp.hostname not in (host, ip, "localhost",
                                               "127.0.0.1"):
                            continue
                        if sp.port not in (None, port):
                            continue
                        np = sp.path or "/"
                        if sp.query:
                            np += "?" + sp.query
                        if BINARY_EXT.search(np.split("?")[0]):
                            continue
                        if len(np) > 120 or np in results or np in nxt:
                            continue
                        nxt.add(np)
                batch_new = sorted(nxt)
                new_paths.extend(p for p in batch_new if p not in results)
                frontier = batch_new
            else:
                frontier = []
    # ordered output: seed paths (wordlist order) first, then BFS discoveries
    ordered = []
    seen_p: set[str] = set()
    for p in [seed_path] + CRAWL_PATHS:
        if p in results and p not in seen_p:
            seen_p.add(p)
            ordered.append(results[p])
    for p in new_paths:
        if p in results and p not in seen_p:
            seen_p.add(p)
            ordered.append(results[p])
    # 404s are expected noise for a wordlist crawl; demote them to the end
    ordered = [e for e in ordered if e.get("status") != 404] + \
        [e for e in ordered if e.get("status") == 404]
    out["endpoints"] = ordered[:40]
    dropped += max(0, len(ordered) - 40)

    # stage 5: sensitive paths
    sensitive = []
    if baseline and time.monotonic() < deadline - 10:
        budget = MAX_REQUESTS - (len(results) + len(sensitive))
        todo = [p for p in SENSITIVE_PATHS
                if p not in results][: max(0, budget)]
        with cf.ThreadPoolExecutor(8) as ex:
            futs = {ex.submit(probe, p): p for p in todo
                    if requests < MAX_REQUESTS}
            for fut in cf.as_completed(futs):
                p = futs[fut]
                try:
                    entry = fut.result()
                except Exception as e:
                    entry = {"path": p, "error": err_note(e)}
                requests += 1
                if entry.get("status") in (200, 204, 301, 302):
                    s: dict = {"path": p, "status": entry["status"]}
                    excerpt = entry.get("excerpt")
                    if excerpt:
                        s["excerpt"] = excerpt[:120]
                    sensitive.append(s)
        sensitive.sort(key=lambda s: SENSITIVE_PATHS.index(
            s["path"]) if s["path"] in SENSITIVE_PATHS else 999)
    out["sensitive"] = sensitive[:16]

    # derived: errors (404s are wordlist noise; signal = 5xx and auth)
    errors = []
    for entry in ordered:
        st = entry.get("status")
        if st is None or not entry.get("excerpt"):
            continue
        if st >= 500 or st in (401, 403):
            errors.append({"path": entry["path"], "status": st,
                           "excerpt": entry["excerpt"][:160]})
        if len(errors) >= 8:
            break
    out["errors"] = errors

    # derived: interesting (deterministic salience, no verdicts)
    interesting = []

    def add_i(path: str, why: str, extra: dict | None = None):
        item = {"path": path, "why": why}
        if extra:
            item.update(extra)
        interesting.append(item)

    for v in vhosts:
        add_i(v.get("host", ""), "distinct vhost",
              {"status": v.get("status")} if v.get("status") else None)
    for entry in ordered:
        p = entry.get("path", "")
        for form in entry.get("forms", []):
            if form.get("method") == "post" and form.get("fields"):
                add_i(p, "POST form: " + ",".join(form["fields"][:4]))
                break
        else:
            if entry.get("params"):
                add_i(p, "query params: " + ",".join(entry["params"][:4]))
            elif entry.get("status") == 500 and entry.get("excerpt") and \
                    re.search(r"traceback|exception|error",
                              entry["excerpt"], re.I):
                add_i(p, "server error (stack trace)")
            elif entry.get("status") in (401, 403):
                add_i(p, "auth challenge")
    for s in sensitive:
        if s.get("status") in (200, 204):
            note = "sensitive file exposed"
            if s.get("excerpt") and \
                    re.search(r"disallow|password|secret|token|key",
                              s["excerpt"], re.I):
                note += ": " + s["excerpt"][:60]
            add_i(s["path"], note)
    out["interesting"] = interesting[:10]

    out["stats"] = {
        "requests": requests,
        "dropped": dropped,
        "elapsed_s": round(time.monotonic() - t0, 1),
    }
    return out


# ---------------------------------------------------------------------------
# code mode
# ---------------------------------------------------------------------------

def _iter_files(root: Path, hard_cap: int):
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in sorted(filenames):
            yield Path(dirpath) / fn
            count += 1
            if count >= hard_cap:
                return


def _peek(p: Path, n: int = 8192) -> bytes | None:
    try:
        with p.open("rb") as f:
            return f.read(n)
    except OSError:
        return None


def _is_binary(p: Path) -> bool:
    head = _peek(p)
    return head is None or b"\x00" in head


MAGIC = [
    (b"\xd4\xc3\xb2\xa0", "pcap"),
    (b"\xa1\xb2\x3c\xc4", "pcap"),
    (b"PK\x03\x04", "zip"),
    (b"\x1f\x8b", "gzip"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"SQLite format 3\x00", "sqlite"),
]


def _magic(head: bytes) -> str | None:
    for sig, name in MAGIC:
        if head.startswith(sig):
            return name
    if head[257:262] == b"ustar":
        return "tar"
    return None


def recon_code(root: Path) -> dict:
    t0 = time.monotonic()
    out: dict = {"root": str(root)}
    file_list: list[str] = []
    hits: dict[str, list[dict]] = {}
    entries: list[dict] = []
    read_files = 0

    for p in _iter_files(root, 300):
        rel = str(p.relative_to(root))
        if len(file_list) < 150:
            file_list.append(rel)
        try:
            if p.stat().st_size > 512 * 1024:
                continue
        except OSError:
            continue
        if _is_binary(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            continue
        read_files += 1
        for i, line in enumerate(text.splitlines(), 1):
            for label, rx in SINKS:
                if rx.search(line):
                    hits.setdefault(label, [])
                    if len(hits[label]) < 6:
                        hits[label].append(
                            {"file": rel, "line": i,
                             "snippet": line.strip()[:80]})
                    break
            for label, rx in ENTRY_POINTS:
                if rx.search(line):
                    if len(entries) < 10:
                        entries.append(
                            {"file": rel, "line": i, "label": label,
                             "snippet": line.strip()[:80]})
                    break

    out["files"] = file_list
    out["files_total"] = len(file_list)
    if entries:
        out["entry_points"] = entries
    if hits:
        out["sinks"] = [
            {"label": label, "hits": hs}
            for label, hs in sorted(hits.items())
        ]
    compose = root / "docker-compose.yml"
    if compose.exists():
        try:
            text = compose.read_text(encoding="utf-8", errors="replace")
            out["compose_services"] = re.findall(
                r"^  ([a-z0-9._-]+):\s*$", text, re.M)[:10]
        except OSError:
            pass
    out["stats"] = {
        "files_scanned": read_files,
        "elapsed_s": round(time.monotonic() - t0, 1),
    }
    return out


# ---------------------------------------------------------------------------
# data mode
# ---------------------------------------------------------------------------

def recon_data(root: Path) -> dict:
    t0 = time.monotonic()
    out: dict = {"root": str(root)}
    data_files: list[dict] = []

    for p in _iter_files(root, 200):
        if len(data_files) >= 20:
            break
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size > 64 * 1024 * 1024:
            continue
        head = _peek(p)
        if head is None:
            continue
        rel = str(p.relative_to(root))
        magic = _magic(head)
        if magic or b"\x00" in head:
            data_files.append({
                "file": rel,
                "size_kb": round(size / 1024, 1),
                "format": magic or "binary",
            })
            continue
        entry: dict = {
            "file": rel,
            "size_kb": round(size / 1024, 1),
        }
        lines = 0
        ts_min: str | None = None
        ts_max: str | None = None
        flag_hits: list[str] = []
        hex_count = 0
        hex_sample: str | None = None
        b64_count = 0
        keyval_count = 0
        jsonl_keys: dict[str, str] = {}
        jsonl_lines = 0
        head: list[str] = []
        tail: deque[str] = deque(maxlen=3)
        csv_guess = False
        try:
            with p.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    lines += 1
                    if len(head) < 3:
                        head.append(line.rstrip("\n")[:120])
                    tail.append(line.rstrip("\n")[:120])
                    m = TS_RE.search(line)
                    if m:
                        if ts_min is None:
                            ts_min = m.group(0)
                        ts_max = m.group(0)
                    fm = FLAG_RE.search(line)
                    if fm and len(flag_hits) < 3:
                        flag_hits.append(fm.group(0)[:80])
                    hm = HEX_RE.search(line)
                    if hm:
                        hex_count += 1
                        if hex_sample is None:
                            hex_sample = hm.group(0)[:40]
                    bm = B64_RE.search(line)
                    if bm and not hm:
                        b64_count += 1
                    if KEYVAL_RE.match(line):
                        keyval_count += 1
                    if lines <= 200:
                        stripped = line.strip()
                        if stripped.startswith("{"):
                            try:
                                obj = json.loads(stripped)
                                jsonl_lines += 1
                                if isinstance(obj, dict):
                                    for k, v in list(obj.items())[:8]:
                                        if k not in jsonl_keys:
                                            jsonl_keys[k] = str(v)[:40]
                            except (json.JSONDecodeError, ValueError):
                                pass
                        elif lines == 1 and stripped.count(",") >= 2:
                            csv_guess = True
        except OSError:
            continue
        entry["lines"] = lines
        fmt = "text"
        if jsonl_lines >= 3:
            fmt = "jsonl"
        elif csv_guess:
            fmt = "csv"
        elif ts_min is not None:
            fmt = "log"
        entry["format"] = fmt
        if ts_min:
            entry["ts_first"] = ts_min
            entry["ts_last"] = ts_max
        needles = {}
        if flag_hits:
            needles["flag"] = flag_hits
        if hex_count:
            needles["hex"] = {"count": hex_count, "sample": hex_sample}
        if b64_count:
            needles["b64"] = b64_count
        if keyval_count:
            needles["keyval"] = keyval_count
        if needles:
            entry["needles"] = needles
        if jsonl_keys:
            entry["jsonl_keys"] = jsonl_keys
        entry["head"] = head[:3]
        entry["tail"] = list(tail)
        data_files.append(entry)

    data_files.sort(key=lambda e: (not e.get("needles"), e["file"]))
    out["data_files"] = data_files[:20]
    out["stats"] = {"elapsed_s": round(time.monotonic() - t0, 1)}
    return out
