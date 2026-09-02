"""Tests for the log_triage engine (agent/shlepa_agent/log_triage.py).

Covers the readonly-tools option A acceptance criteria:
1. JSONL: record count, time range, top entities (event/user/host),
   external IP flag, rare single-occurrence values (IOC candidates)
2. plain-text: timestamps, IPs, severity levels, top tokens
3. directory triage: multiple evidence files, non-evidence files skipped
4. output cap: result never exceeds max_output (line boundary + marker)
5. safety: read-only (content + mtime untouched), missing path is a
   compact error string, never raises
6. determinism: same input, same output
"""

import json
from pathlib import Path

from shlepa_agent.log_triage import DEFAULT_MAX_OUTPUT, log_triage


def _evt(eid, t, user, comp, ip, proc):
    return json.dumps(
        {
            "EventID": eid,
            "TimeCreated": t,
            "SubjectUserName": user,
            "Computer": comp,
            "IP": ip,
            "Process": proc,
        }
    )


SOC_JSONL = "\n".join(
    [
        _evt(4624, "2026-04-17T08:01:00", "t.nguyen", "WS-HR-20", "10.0.0.5", "logonui.exe"),
        _evt(4688, "2026-04-17T08:02:00", "t.nguyen", "WS-HR-20", "10.0.0.5", "svchost.exe"),
        _evt(4688, "2026-04-17T14:03:00", "admin", "WS-HR-20", "10.0.0.5", "powershell.exe"),
        _evt(4688, "2026-04-17T14:04:00", "admin", "DC-01", "203.0.113.9", "powershell.exe"),
        _evt(4625, "2026-04-17T14:05:00", "svc_backup", "DC-01", "198.51.100.23", "vssadmin.exe"),
        _evt(4624, "2026-04-17T14:06:00", "t.nguyen", "WS-HR-20", "10.0.0.5", "explorer.exe"),
    ]
) + "\n"

WEB_LOG = """\
2026-04-17 09:00:00 10.0.0.5 GET /index.html 200
2026-04-17 09:01:00 10.0.0.6 GET /api/login 401
2026-04-17 09:02:00 10.0.0.6 GET /api/login 401
2026-04-17 14:03:00 203.0.113.7 POST /api/upload 500
"""


def _w(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_jsonl_entities_and_iocs(tmp_path: Path):
    f = _w(tmp_path, "events.jsonl", SOC_JSONL)
    out = log_triage(str(f), workdir=tmp_path)
    assert "events.jsonl (6 rec, jsonl" in out
    assert "time: 2026-04-17T08:01:00 .. 2026-04-17T14:06:00" in out
    assert "events: 4688 (3) 4624 (2) 4625 (1)" in out
    assert "users: t.nguyen (3) admin (2) svc_backup (1)" in out
    assert "hosts: WS-HR-20 (4) DC-01 (2)" in out
    assert "svchost.exe" in out or "powershell.exe" in out
    # external IPs flagged, private ones counted
    assert "[ext] 203.0.113.9 (1) 198.51.100.23 (1)" in out
    # rare single-occurrence values are listed as IOC candidates
    assert "rare (seen once)" in out
    assert "user=svc_backup" in out
    assert "host=DC-01" not in out  # seen twice
    # IPs are not part of the rare-entity categories
    assert "ip=" not in out.split("rare (seen once)")[1]


def test_text_log_tokens_and_levels(tmp_path: Path):
    f = _w(tmp_path, "web.log", WEB_LOG + "\n2026-04-17 14:03:01 ERROR upload failed\n")
    out = log_triage(str(f), workdir=tmp_path)
    assert "web.log (5 rec, text" in out
    assert "time: 2026-04-17 09:00:00 .. 2026-04-17 14:03:01" in out
    assert "[ext] 203.0.113.7 (1)" in out
    assert "levels: ERROR (1)" in out
    assert "top tokens" in out and "GET" in out and "/api/login" in out


def test_directory_triage_and_cap(tmp_path: Path):
    _w(tmp_path, "a.jsonl", SOC_JSONL)
    _w(tmp_path, "b.log", WEB_LOG)
    _w(tmp_path, "not_evidence.pdf", "binary")  # skipped: extension
    out = log_triage(str(tmp_path), workdir=tmp_path)
    assert "2 file(s)" in out
    assert "a.jsonl" in out and "b.log" in out
    assert "not_evidence" not in out
    assert len(out) <= DEFAULT_MAX_OUTPUT + 60  # marker overhead


def test_output_cap_with_many_files(tmp_path: Path):
    for i in range(20):  # more than MAX_FILES: capped with a note
        _w(tmp_path, f"f{i:02d}.jsonl", SOC_JSONL)
    out = log_triage(str(tmp_path), workdir=tmp_path)
    assert "8 of 20 files shown" in out
    assert len(out) <= DEFAULT_MAX_OUTPUT + 60


def test_missing_path_is_a_compact_error(tmp_path: Path):
    out = log_triage("nope.jsonl", workdir=tmp_path)
    assert out.startswith("log_triage: path not found")


def test_read_only_and_deterministic(tmp_path: Path):
    f = _w(tmp_path, "events.jsonl", SOC_JSONL)
    before = (f.read_bytes(), f.stat().st_mtime_ns)
    out1 = log_triage(str(f), workdir=tmp_path)
    out2 = log_triage(str(f), workdir=tmp_path)
    assert out1 == out2
    after = (f.read_bytes(), f.stat().st_mtime_ns)
    assert before == after


def test_hour_spike_reported(tmp_path: Path):
    lines = []
    for h in (8, 9, 10):  # quiet hours
        for m in range(3):
            lines.append(
                json.dumps(
                    {
                        "EventID": 4624,
                        "TimeCreated": f"2026-04-17T{h:02d}:{m:02d}:00",
                        "SubjectUserName": "u",
                    }
                )
            )
    for m in range(30):  # spike hour
        lines.append(
            json.dumps(
                {
                    "EventID": 4688,
                    "TimeCreated": f"2026-04-17T14:{m:02d}:00",
                    "SubjectUserName": "x",
                }
            )
        )
    f = _w(tmp_path, "spike.jsonl", "\n".join(lines) + "\n")
    out = log_triage(str(f), workdir=tmp_path)
    assert "peak 2026-04-17T14:00 (30 rec)" in out
    assert "≈ 10× median" in out
