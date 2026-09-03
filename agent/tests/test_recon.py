"""Tests for tools/recon.py (deterministic attack-surface recon).

Covers the tool contract: valid compact JSON within the 8192-byte cap,
deterministic output (modulo stats), vhost/banner discovery, code-surface
sink detection, data-surface needles, and fail-safe behavior on a dead
target. Fixtures are inline (ephemeral ports, tmp_path) so the suite stays
hermetic.
"""

import json
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from shlepa_agent.recon import recon_web, scan_ports

RECON = Path(__file__).resolve().parents[1] / "tools" / "recon.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "recon"
WEB_GOLDEN_PORT = 18473  # fixed port used by the web golden (gen_goldens.py)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    """Minimal target: default app + distinct 'internal' vhost."""

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html"):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Server", "TestServer/1.0")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        path = self.path.split("?")[0]
        if host == "internal":
            return self._send(
                200, "<html><title>Internal Portal</title>hidden area</html>")
        if path == "/":
            return self._send(
                200,
                "<html><title>Main</title>"
                '<form action="/login" method="post">'
                '<input name="user"><input name="pass"></form></html>')
        if path == "/login":
            return self._send(
                200,
                "<html><title>Login</title>"
                '<form action="/login" method="post">'
                '<input name="user"><input name="pass"></form></html>')
        if path == "/search":
            return self._send(200, '{"results": []}', "application/json")
        if path == "/admin":
            return self._send(
                500,
                "<html><title>500</title><pre>Traceback (most recent call "
                "last):\nZeroDivisionError: division by zero</pre></html>")
        if path == "/robots.txt":
            return self._send(
                200, "User-agent: *\nDisallow: /admin\n", "text/plain")
        return self._send(404, "<html><title>404</title>nf</html>")


def _wait_ready(port: int) -> None:
    for _ in range(200):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            threading.Event().wait(0.02)
    raise RuntimeError(f"server on port {port} did not come up")


def _start_web_server(handler=_Handler, port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    _wait_ready(port)
    return server, port


def _start_banner_server() -> tuple[socket.socket, int]:
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)
    port = srv.getsockname()[1]

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            try:
                c.sendall(b"SSH-2.0-TestBanner_1.0\r\n")
            except OSError:
                pass
            c.close()

    threading.Thread(target=serve, daemon=True).start()
    return srv, port


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def run_recon(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RECON), *args],
        capture_output=True, text=True, timeout=180, check=False)


# ---------------------------------------------------------------------------
# web mode
# ---------------------------------------------------------------------------

def test_web_mode_full():
    server, port = _start_web_server()
    try:
        proc = run_recon(f"http://127.0.0.1:{port}/")
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)

        # contract: valid compact JSON within the hard cap
        assert len(proc.stdout.encode()) <= 8192

        # base http + derived sections
        assert out["http"]["status"] == 200
        assert out["http"]["server"] == "TestServer/1.0"
        assert out["http"]["title"] == "Main"

        # vhost discovery by signature diff
        hosts = [v["host"] for v in out["vhosts"]]
        assert "internal" in hosts
        internal = next(v for v in out["vhosts"] if v["host"] == "internal")
        assert internal["title"] == "Internal Portal"

        # endpoint inventory: form parsed, json typed, 500 excerpted
        eps = {e["path"]: e for e in out["endpoints"] if e.get("status")}
        assert eps["/"]["forms"][0]["method"] == "post"
        assert eps["/"]["forms"][0]["fields"] == ["user", "pass"]
        assert eps["/search"].get("type") == "application/json"
        assert eps["/admin"]["status"] == 500
        assert "Traceback" in eps["/admin"]["excerpt"]

        # 404 wordlist noise is demoted to the end
        statuses = [e.get("status") for e in out["endpoints"]
                    if e.get("status")]
        if 404 in statuses:
            first_signal = next(
                i for i, s in enumerate(statuses) if s != 404)
            last_404 = max(i for i, s in enumerate(statuses) if s == 404)
            assert first_signal < last_404

        # sensitive files exposed with excerpts
        sens = {s["path"]: s for s in out["sensitive"]}
        assert sens["/robots.txt"]["status"] == 200
        assert "Disallow" in sens["/robots.txt"]["excerpt"]

        # errors: 5xx stack trace, 404 noise excluded
        errors = out["errors"]
        assert any(e["path"] == "/admin" and e["status"] == 500
                   for e in errors)
        assert all(e["status"] != 404 for e in errors)

        # interesting: vhost + form + 500 + sensitive
        whys = " ".join(i["why"] for i in out["interesting"])
        assert "vhost" in whys
        assert "POST form" in whys
        assert "stack trace" in whys
        assert "sensitive file exposed" in whys

        # target port is always scanned
        assert str(port) in out["ports_open"]

        assert out["stats"]["requests"] > 50
    finally:
        server.shutdown()
        server.server_close()


def test_scan_ports_passive_banner():
    """A service that speaks first (SSH-style) is labeled with its banner."""
    banner, bport = _start_banner_server()
    try:
        ports = scan_ports("127.0.0.1", bport, time.monotonic() + 30)
        assert "TestBanner" in ports.get(str(bport), "")
    finally:
        banner.close()


def test_web_mode_deterministic():
    server, port = _start_web_server()
    try:
        a = json.loads(run_recon(f"http://127.0.0.1:{port}/").stdout)
        b = json.loads(run_recon(f"http://127.0.0.1:{port}/").stdout)
        a.pop("stats")
        b.pop("stats")
        assert a == b
    finally:
        server.shutdown()
        server.server_close()


def test_web_mode_dead_target():
    port = _closed_port()
    proc = run_recon(f"http://127.0.0.1:{port}/")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert "error" in out["http"]
    assert "ConnectionRefused" in out["http"]["error"]
    assert out["vhosts"] == []
    assert out["endpoints"] == []
    assert out["stats"]["requests"] == 0


# ---------------------------------------------------------------------------
# code mode
# ---------------------------------------------------------------------------

def test_code_mode(tmp_path):
    (tmp_path / "main.py").write_text(
        'import os\n'
        'from flask import Flask, request\n\n'
        'app = Flask(__name__)\n\n\n'
        '@app.route("/run")\n'
        'def run():\n'
        '    return str(eval(request.args.get("e")))\n\n\n'
        '@app.route("/ping")\n'
        'def ping():\n'
        '    return str(os.system(request.args.get("c")))\n')
    (tmp_path / "config.py").write_text(
        'PASSWORD = "hunter2secret"\n')
    (tmp_path / "db.py").write_text(
        'cur.execute(f"SELECT * FROM t WHERE n = \'{name}\'")\n')

    proc = run_recon("--code", str(tmp_path))
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert len(proc.stdout.encode()) <= 8192

    sinks = {s["label"]: s["hits"] for s in out.get("sinks", [])}
    for label in ("eval", "os.system", "hardcoded secret",
                  "raw SQL f-string"):
        assert label in sinks, f"missing sink {label}: {sorted(sinks)}"
    assert sinks["eval"][0]["file"] == "main.py"
    assert "eval(" in sinks["eval"][0]["snippet"]

    entries = out.get("entry_points", [])
    assert any(e["label"] == "Flask app" for e in entries)
    assert sum(1 for e in entries if e["label"] == "route") == 2


# ---------------------------------------------------------------------------
# data mode
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CLI parity against golden outputs
#
# Goldens in fixtures/recon/ were generated from the pre-refactor CLI
# (regenerate with: python3 tests/fixtures/recon/gen_goldens.py). They pin
# the CLI contract across the engine extraction into shlepa_agent.recon.
# Volatile fields excluded: stats.elapsed_s (timing), root (absolute
# checkout path), ports_open (depends on what else listens on the host).
# ---------------------------------------------------------------------------


def _strip_volatile(obj: dict) -> dict:
    obj = dict(obj)
    obj.pop("root", None)
    stats = dict(obj.get("stats", {}))
    stats.pop("elapsed_s", None)
    obj["stats"] = stats
    return obj


def test_code_cli_parity():
    proc = run_recon("--code", str(FIXTURES / "code_fixture"))
    assert proc.returncode == 0, proc.stderr
    live = _strip_volatile(json.loads(proc.stdout))
    golden = _strip_volatile(
        json.loads((FIXTURES / "code.golden.json").read_text()))
    assert live == golden


def test_data_cli_parity():
    proc = run_recon("--data", str(FIXTURES / "data_fixture"))
    assert proc.returncode == 0, proc.stderr
    live = _strip_volatile(json.loads(proc.stdout))
    golden = _strip_volatile(
        json.loads((FIXTURES / "data.golden.json").read_text()))
    assert live == golden


def test_web_cli_parity():
    try:
        server, port = _start_web_server(port=WEB_GOLDEN_PORT)
    except OSError:
        pytest.skip(f"port {WEB_GOLDEN_PORT} is busy on this host")
    try:
        proc = run_recon(f"http://127.0.0.1:{port}/")
        assert proc.returncode == 0, proc.stderr
        live = json.loads(proc.stdout)
        # the fixture's own port must be scanned open
        assert str(port) in live["ports_open"]
        live.pop("stats", None)   # elapsed_s volatile
        live.pop("ports_open", None)  # host-dependent
        golden = json.loads((FIXTURES / "web.golden.json").read_text())
        assert live == golden
    finally:
        server.shutdown()
        server.server_close()


def test_engine_exposes_entries():
    import shlepa_agent.recon as engine

    for name in ("recon_web", "recon_code", "recon_data", "render",
                 "err_note"):
        assert callable(getattr(engine, name)), name


def test_engine_stdlib_only():
    """The engine must stay importable in a bare stdlib python (task env)."""
    import ast

    import shlepa_agent.recon as engine

    tree = ast.parse(Path(engine.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in sys.stdlib_module_names, \
                    alias.name
        elif isinstance(node, ast.ImportFrom):
            assert node.level > 0 or \
                (node.module or "").split(".")[0] in sys.stdlib_module_names, \
                node.module


def test_engine_matches_cli():
    """The CLI wrapper must be a thin passthrough over the engine."""
    import shlepa_agent.recon as engine

    for flag, fixture, fn in (
        ("--code", "code_fixture", engine.recon_code),
        ("--data", "data_fixture", engine.recon_data),
    ):
        proc = run_recon(flag, str(FIXTURES / fixture))
        assert proc.returncode == 0, proc.stderr
        live = _strip_volatile(fn(FIXTURES / fixture))
        cli = _strip_volatile(json.loads(proc.stdout))
        assert live == cli


class _SlowHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(2.0)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
        except OSError:
            # client timed out mid-sleep: the connection is gone; that is
            # exactly the behavior under test
            pass

    def log_message(self, *args):
        pass


def test_web_mode_slow_target_deadline():
    """A slow target must not blow the 30s per-call tool wall.

    The server sleeps 2s per request, so vhost/crawl eat the budget;
    recon_web must finish with a capped JSON, per-stage skip notes, and
    no exception (issue #106).
    """
    server, port = _start_web_server(_SlowHandler)
    try:
        t0 = time.monotonic()
        out = recon_web(f"http://127.0.0.1:{port}/")
        wall = time.monotonic() - t0
    finally:
        server.shutdown()
        server.server_close()
    # completes well before the 30s per-call tool wall
    assert out["stats"]["elapsed_s"] <= 27
    assert wall <= 28
    # full JSON shape, all fail-safe sections present
    for key in ("url", "ports_open", "http", "vhosts", "endpoints",
                "sensitive", "errors", "interesting", "stats"):
        assert key in out
    # base probe succeeds within its 5s timeout despite the 2s sleep
    assert out["http"]["status"] == 200
    # the crawl starts before the deadline on this fixture
    assert len(out["endpoints"]) > 0
    # the last stage is always past the deadline on this fixture
    assert out["sensitive_note"] == "skipped (deadline)"
    # the target port is open but silent during the 0.5s banner window
    # (the server sleeps 2s before responding): it must be labeled open
    # without hanging the scan
    assert str(port) in out["ports_open"]


def test_data_mode(tmp_path):
    (tmp_path / "notes.txt").write_text(
        "case_id=IR-1\n"
        "flag{deadbeef}\n"
        "deadbeefcafe0123deadbeefcafe0123deadbeef\n")
    lines = [json.dumps({
        "ts": f"2026-05-01T10:00:{i:02d}Z",
        "event": "upload" if i % 2 else "login",
    }) for i in range(10)]
    (tmp_path / "app.jsonl").write_text("\n".join(lines) + "\n")
    (tmp_path / "capture.pcap").write_bytes(
        b"\xd4\xc3\xb2\xa0" + b"\x00" * 32)

    proc = run_recon("--data", str(tmp_path))
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    files = {f["file"]: f for f in out["data_files"]}

    assert files["notes.txt"]["format"] == "text"
    assert files["notes.txt"]["needles"]["flag"] == ["flag{deadbeef}"]
    assert files["notes.txt"]["needles"]["hex"]["count"] == 1
    assert files["notes.txt"]["needles"]["keyval"] == 1

    assert files["app.jsonl"]["format"] == "jsonl"
    assert files["app.jsonl"]["ts_first"] == "2026-05-01T10:00:00"
    assert files["app.jsonl"]["ts_last"] == "2026-05-01T10:00:09"
    assert "event" in files["app.jsonl"]["jsonl_keys"]

    # magic-byte detection for forensically relevant containers
    assert files["capture.pcap"]["format"] == "pcap"
