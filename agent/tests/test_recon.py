"""Tests for the bundled deterministic recon script (agent/tools/recon.py).

The script is exercised as a subprocess (its real entry point) against a
local fixture server; no network traffic beyond loopback, except one
blackhole-IP test that relies on connection timeouts.
"""

import importlib.util
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fixture_server import start_fixture_server

RECON = Path(__file__).resolve().parent.parent / "tools" / "recon.py"
MAX_OUTPUT_BYTES = 3072  # "3 KB" per the issue contract

_spec = importlib.util.spec_from_file_location("recon_under_test", RECON)
recon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recon)


def run_recon(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RECON), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(RECON.parent.parent),
    )


def strip_timing(data: dict) -> dict:
    """Copy of the recon output without the non-deterministic timing block."""
    return {k: v for k, v in data.items() if k != "timing"}


@pytest.fixture
def fixture():
    server, base_url, port = start_fixture_server()
    try:
        yield base_url, port
    finally:
        server.shutdown()
        server.server_close()


def test_recon_json_contract_and_size(fixture):
    base_url, port = fixture
    proc = run_recon(base_url)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert len(proc.stdout.encode("utf-8")) <= MAX_OUTPUT_BYTES

    for key in ("target", "host", "ports", "http", "fingerprint", "endpoints", "timing"):
        assert key in data

    # Stage 1: the fixture port is open.
    open_ports = [p["port"] for p in data["ports"]["open"]]
    assert port in open_ports

    # Stage 2: the homepage was probed.
    assert data["http"]["http_status"] == 200
    assert data["http"]["title"] == "Acme Portal"

    # Stage 3: nginx server header, generator meta, JS library signatures.
    assert data["fingerprint"]["server"].startswith("nginx/1.25.4")
    assert data["fingerprint"]["generator"] == "Acme CMS 3.2"
    assert "jquery" in data["fingerprint"]["js"]
    assert "bootstrap" in data["fingerprint"]["js"]
    assert "wordpress" not in data["fingerprint"]["frameworks"]

    # Stage 4: crawl found the pages; wordlist/crawl found the high-value paths.
    page_paths = {p["path"] for p in data["endpoints"]["pages"]}
    assert "/" in page_paths
    assert "/login.html" in page_paths
    # JS path extraction from the login page body.
    assert "/api/auth/login" in data["endpoints"]["links"]
    interesting = {p["path"] for p in data["endpoints"]["interesting"]}
    assert {"/admin", "/secret.txt", "/robots.txt", "/api/health", "/api/users"} <= interesting


def test_recon_deterministic(fixture):
    base_url, _ = fixture
    first = json.loads(run_recon(base_url).stdout)
    second = json.loads(run_recon(base_url).stdout)
    assert strip_timing(first) == strip_timing(second)


def test_recon_stage_failure_emits_all_sections():
    # Find a port that is definitely closed, then aim the recon at it:
    # every stage must still emit its section (fail-safe contract).
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    closed_port = probe.getsockname()[1]
    probe.close()

    proc = run_recon(f"http://127.0.0.1:{closed_port}/")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    for key in ("ports", "http", "fingerprint", "endpoints", "timing"):
        assert key in data
    assert data["http"]["status"] == "error"
    assert data["fingerprint"]["js"] == []


def test_recon_hard_timeout_blackhole():
    # RFC 5737 TEST-NET-1 is unroutable: every probe hits its timeout.
    # The run must respect the --timeout cap and still print full JSON.
    started = time.monotonic()
    proc = run_recon("10.255.255.1", "--timeout", "3", timeout=60)
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, proc.stderr
    assert elapsed < 20, f"recon exceeded the timeout cap ({elapsed:.1f}s)"
    data = json.loads(proc.stdout)
    for key in ("ports", "http", "fingerprint", "endpoints", "timing"):
        assert key in data
    assert data["http"]["status"] == "error"
    assert data["endpoints"].get("status") in ("skipped", "ok")


def test_recon_bare_host_port_target(fixture):
    _, port = fixture
    proc = run_recon(f"127.0.0.1:{port}")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["target"] == f"http://127.0.0.1:{port}/"
    assert data["http"]["http_status"] == 200


def test_parse_target():
    assert recon._parse_target("example.com") == (
        "http://example.com/",
        "example.com",
        None,
    )
    # Bare host:port defaults to http (local targets are usually plain http),
    # unless the port is 443.
    assert recon._parse_target("h:8443") == ("http://h:8443/", "h", 8443)
    assert recon._parse_target("h:443") == ("https://h:443/", "h", 443)
    assert recon._parse_target("https://h:8443/x?q=1") == (
        "https://h:8443/x?q=1",
        "h",
        8443,
    )
    with pytest.raises(ValueError):
        recon._parse_target("ftp://example.com")
    with pytest.raises(ValueError):
        recon._parse_target("example.com:notaport")


def test_trim_to_budget_fits_cap():
    result = {
        "target": "http://127.0.0.1:8000/",
        "host": "127.0.0.1",
        "ports": {
            "status": "ok",
            "open": [{"port": i, "service": "x"} for i in range(200)],
            "scanned": 100,
        },
        "http": {
            "status": "ok",
            "url": "http://127.0.0.1:8000/",
            "http_status": 200,
            "headers": {},
            "title": "t",
        },
        "fingerprint": {
            "server": "s",
            "x_powered_by": None,
            "generator": None,
            "js": [f"lib{i}" for i in range(100)],
            "frameworks": [],
        },
        "endpoints": {
            "status": "ok",
            "pages": [{"path": f"/p{i}", "status": 200} for i in range(100)],
            "interesting": [{"path": f"/i{i}", "status": 200} for i in range(100)],
            "links": [f"/link{i}" for i in range(100)],
        },
        "timing": {"total_sec": 1.0},
    }
    recon._trim_to_budget(result)
    packed = json.dumps(result, separators=(",", ":")).encode("utf-8")
    assert len(packed) <= 3000
