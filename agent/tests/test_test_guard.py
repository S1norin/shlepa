"""w3-6: test-file hash guard (tamper invalidates results).

Unit tests for the guard module + a stub-pipeline test where WORK
mutates tests/test.sh via bash and the exit re-hash flags test_tamper.
"""

import asyncio
import json
import logging

import pytest

from shlepa_agent.test_guard import (
    bootstrap_test_hashes,
    check_test_hashes,
)
from stub_server import stub_state


@pytest.fixture
def events():
    from shlepa_agent.log import LOGGER

    records: list[dict] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                records.append(json.loads(record.getMessage()))
            except (TypeError, ValueError):
                pass

    handler = _Collector()
    old_level = LOGGER.level
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    try:
        yield records
    finally:
        LOGGER.removeHandler(handler)
        LOGGER.setLevel(old_level)


# -- unit tests -------------------------------------------------------------

def _tree(tmp_path):
    (tmp_path / "tests" / "sub").mkdir(parents=True)
    (tmp_path / "tests" / "test.sh").write_text("echo ok\n")
    (tmp_path / "tests" / "sub" / "check.py").write_text("print(1)\n")
    (tmp_path / "a.test.sh").write_text("echo t\n")
    (tmp_path / "app.py").write_text("print('app')\n")
    (tmp_path / "root_test.sh.bak").write_text("x\n")


def test_bootstrap_selects_only_test_files(tmp_path):
    _tree(tmp_path)
    h = bootstrap_test_hashes(tmp_path)
    assert set(h) == {"tests/test.sh", "tests/sub/check.py", "a.test.sh"}
    assert all(len(v) == 64 for v in h.values())


def test_unchanged_hashes_accepted(tmp_path):
    _tree(tmp_path)
    h = bootstrap_test_hashes(tmp_path)
    assert check_test_hashes(tmp_path, h) == []


def test_modified_file_flagged(tmp_path):
    _tree(tmp_path)
    h = bootstrap_test_hashes(tmp_path)
    (tmp_path / "tests" / "test.sh").write_text("echo hacked\n")
    assert check_test_hashes(tmp_path, h) == ["tests/test.sh"]


def test_deleted_file_flagged(tmp_path):
    _tree(tmp_path)
    h = bootstrap_test_hashes(tmp_path)
    (tmp_path / "a.test.sh").unlink()
    assert check_test_hashes(tmp_path, h) == ["a.test.sh"]


# -- e2e: a tampered test file is flagged at exit ----------------------------

def _run(monkeypatch, stub_openai, tmp_path, agent_cfg, task="t"):
    from shlepa_agent import runner

    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))
    monkeypatch.delenv("SHLEPA_SALVAGE", raising=False)
    return asyncio.run(runner.run_prompt(task, agent_cfg=agent_cfg))


def _script(bash_cmd: str | None):
    """plan -> work (+bash) -> relay -> plan -> work (max_cycles = 2)."""
    from tests.test_snapshot import _plan_step, _relay_step, _work_step

    steps = [_plan_step()]
    if bash_cmd:
        steps.append(
            {"tool_call": {"name": "bash", "arguments": {"command": bash_cmd}}}
        )
    steps += [_work_step(), _relay_step(done=True), _plan_step(), _work_step()]
    return steps


def test_tamper_logged_at_exit(monkeypatch, stub_openai, tmp_path, events):
    from tests.test_snapshot import _cfg

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test.sh").write_text("echo ok\n")
    stub_state["script"] = _script("echo hacked > tests/test.sh")
    _run(monkeypatch, stub_openai, tmp_path, _cfg(tmp_path))

    tamper = [e for e in events if e.get("event") == "test_tamper"]
    assert tamper, "a mutated test file must be flagged at exit"
    assert tamper[0]["files"] == ["tests/test.sh"]
    guard = [e for e in events if e.get("event") == "test_guard"]
    assert guard and guard[0]["files"] == 1


def test_untampered_run_has_no_tamper_event(
    monkeypatch, stub_openai, tmp_path, events
):
    from tests.test_snapshot import _cfg

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test.sh").write_text("echo ok\n")
    stub_state["script"] = _script(None)
    _run(monkeypatch, stub_openai, tmp_path, _cfg(tmp_path))
    assert not any(e.get("event") == "test_tamper" for e in events)
