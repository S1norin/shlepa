"""Unit tests for the mechanical deliverable check (w2-1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shlepa_agent.deliverable_check import (
    ArtifactSpec,
    DeliverableCheck,
    check_deliverable,
)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path


def _check(workdir: Path, **spec: object):
    return check_deliverable(workdir, spec, log=False)


# ---------------------------------------------------------------- valid file
def test_valid_json_file(workdir: Path):
    (workdir / "out.json").write_text(json.dumps({"a": 1, "b": 2}))
    r = _check(workdir, path="out.json", format="json")
    assert r == DeliverableCheck(True, True, True, True, True, "")
    assert r.valid


def test_valid_text_file_absolute_path(workdir: Path):
    f = workdir / "hello.txt"
    f.write_text("hello")
    r = _check(workdir, path=str(f))
    assert r.valid and r.exists and r.non_empty


def test_expected_content_match(workdir: Path):
    (workdir / "hello.txt").write_text("hello\n")
    r = _check(workdir, path="hello.txt", kind="answer", expected_content="hello")
    assert r.valid


def test_expected_content_mismatch(workdir: Path):
    (workdir / "hello.txt").write_text("goodbye")
    r = _check(workdir, path="hello.txt", kind="answer", expected_content="hello")
    assert r.exists and r.non_empty and r.parse_ok and r.keys_ok and not r.valid
    assert "content" in r.reason


# ---------------------------------------------------------------- missing / empty
def test_missing_file(workdir: Path):
    r = _check(workdir, path="nope.txt")
    assert r == DeliverableCheck(
        False, False, False, False, False, "missing: " + str(workdir / "nope.txt")
    )


def test_empty_file(workdir: Path):
    (workdir / "empty.txt").write_text("")
    r = _check(workdir, path="empty.txt")
    assert r.exists and not r.non_empty and not r.valid
    assert "empty" in r.reason


def test_empty_spec_has_no_path(workdir: Path):
    r = _check(workdir, kind="file")
    assert not r.exists and not r.valid
    assert "no path" in r.reason


# ---------------------------------------------------------------- malformed json / keys
def test_malformed_json(workdir: Path):
    (workdir / "bad.json").write_text("{not json")
    r = _check(workdir, path="bad.json", format="json")
    assert r.exists and r.non_empty and not r.parse_ok and not r.valid
    assert "json" in r.reason


def test_json_missing_keys(workdir: Path):
    (workdir / "out.json").write_text(json.dumps({"a": 1}))
    r = _check(workdir, path="out.json", format="json", keys=["a", "b"])
    assert r.parse_ok and not r.keys_ok and not r.valid
    assert "b" in r.reason


def test_json_keys_all_present(workdir: Path):
    (workdir / "out.json").write_text(json.dumps({"a": 1, "b": 2, "c": 3}))
    r = _check(workdir, path="out.json", format="json", keys=["a", "c"])
    assert r.valid


def test_json_keys_on_list(workdir: Path):
    (workdir / "arr.json").write_text("[1, 2]")
    r = _check(workdir, path="arr.json", format="json", keys=["a"])
    assert not r.keys_ok and not r.valid
    assert "keys" in r.reason


# ---------------------------------------------------------------- csv
def test_csv_header_keys(workdir: Path):
    (workdir / "t.csv").write_text("id,name\n1,foo\n")
    assert _check(workdir, path="t.csv", format="csv", keys=["id", "name"]).valid
    r = _check(workdir, path="t.csv", format="csv", keys=["id", "score"])
    assert not r.keys_ok and "score" in r.reason


def test_csv_no_rows(workdir: Path):
    (workdir / "t.csv").write_text("\n")
    r = _check(workdir, path="t.csv", format="csv")
    assert not r.parse_ok and not r.valid


# ---------------------------------------------------------------- patch
def test_patch_ok(workdir: Path):
    (workdir / "fix.patch").write_text("--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n")
    r = _check(workdir, path="fix.patch", format="patch")
    assert r.valid


def test_patch_without_headers(workdir: Path):
    (workdir / "fix.patch").write_text("just some text")
    r = _check(workdir, path="fix.patch", format="patch")
    assert not r.parse_ok and not r.valid
    assert "patch" in r.reason


# ---------------------------------------------------------------- keys on non-checkable format
def test_keys_on_text_rejected(workdir: Path):
    (workdir / "t.txt").write_text("x")
    r = _check(workdir, path="t.txt", format="text", keys=["a"])
    assert not r.keys_ok and not r.valid
    assert "only for json/csv" in r.reason


# ---------------------------------------------------------------- spec conversion
def test_from_any_dict_and_pydantic():
    s = ArtifactSpec.from_any(
        {"kind": "answer", "path": "/a", "keys": ["x", "y"], "expected_content": "1"}
    )
    assert s.kind == "answer" and s.path == "/a"
    assert s.keys == ("x", "y") and s.expected_content == "1"
    assert ArtifactSpec.from_any(None) is None
    s3 = ArtifactSpec.from_any({"path": "p"})  # defaults
    assert s3.kind == "file" and s3.format == "" and s3.keys == () and s3.expected_content is None


def test_from_any_scalar_keys():
    s = ArtifactSpec.from_any({"path": "p", "keys": "solo"})
    assert s.keys == ("solo",)


# ---------------------------------------------------------------- events + lockdown
def test_event_logged(workdir: Path, monkeypatch):
    """The module logger is configured once per process; redirect its
    handler stream to a buffer for deterministic capture."""
    import io
    import logging

    from shlepa_agent.log import LOGGER, _configure_logging

    _configure_logging()
    buf = io.StringIO()
    saved = []  # (handler, original stream)
    for h in LOGGER.handlers:
        if isinstance(h, logging.StreamHandler):
            saved.append((h, h.stream))
            h.stream = buf
    try:
        (workdir / "o.json").write_text("{}")
        check_deliverable(workdir, {"path": "o.json", "format": "json"})
    finally:
        for h, original in saved:
            h.stream = original
    out = buf.getvalue()
    assert "deliverable_check" in out
    assert '"valid": true' in out or '"valid":true' in out


def test_no_subprocess_or_network(workdir: Path, monkeypatch):
    """Locked-down test: subprocess and socket are blown away; the check
    must still work (file reads only)."""

    import socket

    def _boom(*a, **k):
        raise AssertionError("subprocess or network used by deliverable_check")

    import subprocess

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(socket, "socket", _boom)

    (workdir / "o.json").write_text(json.dumps({"k": 1}))
    r = _check(workdir, path="o.json", format="json", keys=["k"])
    assert r.valid


def test_kind_does_not_change_file_semantics(workdir: Path):
    """test_command/answer use the same file booleans as file (w2-1 scope)."""
    (workdir / "o.txt").write_text("42")
    for kind in ("file", "test_command", "answer"):
        assert _check(workdir, kind=kind, path="o.txt").valid


# ---------------------------------------------------------------- sink keyword check (#128)

TASKS_DIR = Path(__file__).resolve().parents[2] / "tasks"


def _copy_rel(src_root: Path, dst_root: Path, rel: str) -> None:
    """Copy one file from a task's environment/app tree into workdir,
    preserving the path relative to the app root (== /app inside the env)."""
    target = dst_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((src_root / rel).read_bytes())


def _write_report(workdir: Path, critical_operation: object) -> None:
    report = {
        "vulnerability_found": True,
        "vulnerability_type": "test",
        "severity": "high",
        "entry_point": {"file": "f.py", "line": 1},
        "critical_operation": critical_operation,
        "data_flow": [],
        "root_cause": "r",
        "impact": "i",
        "recommendation": "rec",
    }
    (workdir / "report.json").write_text(json.dumps(report))


AIRFLOW_REL = "airflow-core/src/airflow/example_dags/example_xcom.py"
MUSTACHE_REL = "libs/core/langchain_core/utils/mustache.py"
STRING_REL = "libs/core/langchain_core/prompts/string.py"


def _airflow_workdir(workdir: Path) -> Path:
    src = TASKS_DIR / "bench-vulngym-airflow-xcom-shell-injection" / "environment" / "app"
    if not (src / AIRFLOW_REL).is_file():
        pytest.skip("airflow task source not present")
    _copy_rel(src, workdir, AIRFLOW_REL)
    return workdir


def _langchain_workdir(workdir: Path) -> Path:
    src = TASKS_DIR / "bench-vulngym-langchain-template-injection" / "environment" / "app"
    if not (src / MUSTACHE_REL).is_file() or not (src / STRING_REL).is_file():
        pytest.skip("langchain task source not present")
    _copy_rel(src, workdir, MUSTACHE_REL)
    _copy_rel(src, workdir, STRING_REL)
    return workdir


def test_sink_wrong_line_rejected(workdir: Path):
    """A report pointing at a line whose window has no sink keywords is
    invalid, with the #128 hint in the reason."""
    (workdir / "src.py").write_text(
        "def produce():\n"
        "    return value\n"
        "\n"
        "\n"
        "\n"
        "\n"
        "\n"
        "\n"
        "def sink():\n"
        "    subprocess.run(cmd)\n"
    )
    # line 1 (produce): window 1-7 has no keywords; line 9 has the sink
    _write_report(workdir, {"file": "src.py", "line": 1})
    r = check_deliverable(
        workdir, {"path": "report.json", "format": "json"},
        sink={"keywords": "bash|subprocess|xcom_pull"}, log=False,
    )
    assert not r.valid and not r.sink_ok
    assert r.exists and r.non_empty and r.parse_ok
    assert "sink" in r.reason
    assert "source side" in r.reason
    # the correct coordinate passes
    _write_report(workdir, {"file": "src.py", "line": 9})
    r = check_deliverable(
        workdir, {"path": "report.json", "format": "json"},
        sink={"keywords": "bash|subprocess|xcom_pull"}, log=False,
    )
    assert r.valid and r.sink_ok


def test_sink_reference_line_passes_airflow(workdir: Path):
    """The reference report's coordinate (80-87, the BashOperator window)
    must pass."""
    _airflow_workdir(workdir)
    _write_report(workdir, {"file": AIRFLOW_REL, "line": "80-87"})
    r = check_deliverable(
        workdir, {"path": "report.json", "format": "json"},
        sink={"keywords": "bash|subprocess|xcom_pull"}, log=False,
    )
    assert r.valid and r.sink_ok and r.reason == ""


def test_sink_reference_line_passes_langchain(workdir: Path):
    """mustache.py:382 (getattr fallback) and string.py:111 (formatter
    entry) both carry sink keywords under the tolerance window."""
    _langchain_workdir(workdir)
    _write_report(workdir, {"file": MUSTACHE_REL, "line": 382})
    r = check_deliverable(
        workdir, {"path": "report.json", "format": "json"},
        sink={"keywords": "getattr|__getitem__|format|render"}, log=False,
    )
    assert r.valid and r.sink_ok
    _write_report(workdir, {"file": STRING_REL, "line": 111})
    r = check_deliverable(
        workdir, {"path": "report.json", "format": "json"},
        sink={"keywords": "getattr|__getitem__|format|render"}, log=False,
    )
    assert r.valid and r.sink_ok


def test_sink_wrong_line_rejected_langchain(workdir: Path):
    _langchain_workdir(workdir)
    # mustache.py line 1 has no sink keywords in its window
    _write_report(workdir, {"file": MUSTACHE_REL, "line": 1})
    r = check_deliverable(
        workdir, {"path": "report.json", "format": "json"},
        sink={"keywords": "getattr|__getitem__|format|render"}, log=False,
    )
    assert not r.valid and not r.sink_ok
    assert "source side" in r.reason


def test_sink_missing_field(workdir: Path):
    _airflow_workdir(workdir)
    _write_report(workdir, {"file": AIRFLOW_REL})  # no line
    r = check_deliverable(
        workdir, {"path": "report.json", "format": "json"},
        sink={"keywords": "bash|subprocess|xcom_pull"}, log=False,
    )
    assert not r.valid and not r.sink_ok
    assert "critical_operation" in r.reason


def test_sink_missing_field_entirely(workdir: Path):
    (workdir / "out.json").write_text(json.dumps({"a": 1}))
    r = check_deliverable(
        workdir, {"path": "out.json", "format": "json"},
        sink={"keywords": "bash"}, log=False,
    )
    assert not r.valid and not r.sink_ok
    assert "critical_operation" in r.reason


def test_sink_reported_file_not_found(workdir: Path):
    (workdir / "report.json").write_text(json.dumps(
        {"critical_operation": {"file": "nope.py", "line": 5}}
    ))
    r = check_deliverable(
        workdir, {"path": "report.json", "format": "json"},
        sink={"keywords": "bash"}, log=False,
    )
    assert not r.valid and not r.sink_ok
    assert "not found" in r.reason


def test_sink_no_config_is_noop(workdir: Path):
    """Tasks without a keyword map are unaffected."""
    (workdir / "out.json").write_text(json.dumps({"critical_operation": {}}))
    r = _check(workdir, path="out.json", format="json")
    assert r.valid and r.sink_ok


def test_sink_invalid_pattern_skips_check(workdir: Path):
    """A broken pattern in task metadata must never block a run."""
    (workdir / "out.json").write_text(json.dumps(
        {"critical_operation": {"file": "x.py", "line": 1}}
    ))
    (workdir / "x.py").write_text("pass\n")
    r = check_deliverable(
        workdir, {"path": "out.json", "format": "json"},
        sink={"keywords": "([unclosed"}, log=False,
    )
    assert r.valid and r.sink_ok


def test_sink_tolerance_expands_window(workdir: Path):
    """tolerance=5 pulls a keyword 5 lines away into the window."""
    (workdir / "src.py").write_text("x = 1\n" * 9 + "subprocess.run('ls')\n")
    _write_report(workdir, {"file": "src.py", "line": 1})
    r = check_deliverable(
        workdir, {"path": "report.json", "format": "json"},
        sink={"keywords": "subprocess", "tolerance": 5}, log=False,
    )
    assert not r.sink_ok
    r = check_deliverable(
        workdir, {"path": "report.json", "format": "json"},
        sink={"keywords": "subprocess", "tolerance": 9}, log=False,
    )
    assert r.valid and r.sink_ok


def test_sink_from_any_variants():
    from shlepa_agent.deliverable_check import SinkCheck

    assert SinkCheck.from_any(None) is None
    assert SinkCheck.from_any({}) is None
    assert SinkCheck.from_any(5) is None
    assert SinkCheck.from_any("bash|sh") == SinkCheck(keywords="bash|sh")
    s = SinkCheck.from_any({"keywords": "x", "field": "op", "tolerance": "3"})
    assert (s.keywords, s.field, s.tolerance) == ("x", "op", 3)
    s = SinkCheck.from_any({"keywords": "x", "tolerance": "bogus"})
    assert s.tolerance == 2
    assert SinkCheck.from_any({"keywords": "  "}) is None
