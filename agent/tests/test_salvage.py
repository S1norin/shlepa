"""w2-3: the SALVAGE route — write-only rescue when WORK left the
deliverable missing/empty, harness-persisted final_result.body, and the
SHLEPA_SALVAGE=0 kill-switch.

Pipeline tests drive the real runner against the stub OpenAI server with a
test config that includes a [phases.salvage] section (so the gate is
configured), exactly like the production config.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from stub_server import stub_state


@pytest.fixture
def events():
    """Collect agent JSON log events for the duration of a test."""
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


def _run(monkeypatch, stub_openai, tmp_path, agent_cfg, task="create hello.txt", salvage: str | None = None):
    from shlepa_agent import runner

    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))
    if salvage is None:
        monkeypatch.delenv("SHLEPA_SALVAGE", raising=False)  # clean default: on
    else:
        monkeypatch.setenv("SHLEPA_SALVAGE", salvage)
    return asyncio.run(runner.run_prompt(task, agent_cfg=agent_cfg))


def _cfg(tmp_path):
    """Test config with a [phases.salvage] section (the production shape)."""
    p = tmp_path / "cfg.toml"
    p.write_text(
        """
[agent]
temp = 0.6
send_temp = true
entry = "plan"
emergency = "emergency"
max_steps = 12

[budget]
max_tokens = 16384
request_timeout = 30.0

[tools.bash]
enabled = true
[tools.read]
enabled = true
[tools.write]
enabled = true
[tools.edit]
enabled = true

[phases.plan]
tools = ["read", "write", "edit", "bash"]
requests = 25
time = 60.0
soft_time = 45.0
soft_tokens = 15000
max_retries = 1

[phases.work]
tools = ["read", "write", "edit", "bash"]
requests = 100
time = 180.0
soft_time = 105.0
max_retries = 1

[phases.salvage]
tools = ["write"]
requests = 5
time = 30.0
max_retries = 0

[phases.commit]
tools = ["read", "write", "edit", "bash"]
requests = 20
time = 45.0
reasoning_effort = "low"
max_retries = 0

[phases.emergency]
tools = ["read", "write", "edit", "bash"]
requests = 20
reasoning_effort = "low"
max_retries = 0

[template]
blocks = ["system", "tools", "task", "extra", "previous_results",
          "phase_prompt", "output_schema", "note"]
""",
        encoding="utf-8",
    )
    from shlepa_agent.config import load_config

    return load_config(p)


def _plan_step():
    return {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "goal": "write hello.txt with the content hello",
                "findings": "the task says the file must contain hello",
                "steps": ["write the file"],
                "artifact_spec": {
                    "kind": "file",
                    "path": "hello.txt",
                    "format": "text",
                    "keys": [],
                    "expected_content": "hello",
                },
            },
        }
    }


def _work_step(deliverable: str = "hello.txt"):
    return {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "summary": "tried to write hello.txt but ran out of time",
                "findings": "",
                "deliverable": deliverable,
                "confidence": 0.3,
            },
        }
    }


def _salvage_step(body: str = "hello", path: str = ""):
    return {
        "tool_call": {
            "name": "final_result",
            "arguments": {"body": body, "path": path},
        }
    }


def _salvage_write_step(path: str = "hello.txt", text: str = "hello\n"):
    return {"tool_call": {"name": "write", "arguments": {"path": path, "text": text}}}


def _review_step():
    return {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "status": "ok",
                "verdict": "done",
                "artifact": "hello.txt",
                "checks": ["re-read -> matches"],
                "hints": [],
                "notes": "wrote hello.txt",
            },
        }
    }


def _phase_starts(events):
    return [
        e["id"]
        for e in events
        if e.get("event") == "phase" and e.get("start")
    ]


# -- AC: harness persist ------------------------------------------------------
def test_salvage_persists_body_when_model_never_wrote(
    monkeypatch, stub_openai, tmp_path, events
):
    stub_state["script"] = [_plan_step(), _work_step(), _salvage_step("hello"), _review_step()]
    output = _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))

    assert output == "wrote hello.txt"
    assert _phase_starts(events) == ["plan", "work", "salvage", "commit"]
    # the harness persisted final_result.body even though the model never
    # called the write tool
    f = tmp_path / "hello.txt"
    assert f.is_file()
    assert f.read_text(encoding="utf-8") == "hello"
    # the mechanical check ran before (missing) and after (valid) the rescue
    checks = [e for e in events if e.get("event") == "deliverable_check"]
    assert len(checks) >= 2
    assert checks[0]["exists"] is False and checks[0]["valid"] is False
    assert checks[-1]["exists"] is True and checks[-1]["valid"] is True
    # the body fallback was persisted (the file was still missing before it)
    assert any(e.get("event") == "salvage_persist" for e in events)


def test_salvage_write_tool_beats_body_persist(
    monkeypatch, stub_openai, tmp_path, events
):
    """A file the model itself wrote wins: no salvage_persist, content kept."""
    # _plan_step's artifact_spec expects "hello" verbatim; the tool write
    # matches it, the (different) body would not — the file must be the
    # tool's content for the re-check to be valid.
    stub_state["script"] = [
        _plan_step(),
        _work_step(),
        _salvage_write_step(path="hello.txt", text="hello"),
        _salvage_step(body="WRONG-BODY-SHOULD-NOT-PERSIST", path="hello.txt"),
        _review_step(),
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))

    f = tmp_path / "hello.txt"
    assert f.read_text(encoding="utf-8") == "hello"
    assert not any(e.get("event") == "salvage_persist" for e in events)
    checks = [e for e in events if e.get("event") == "deliverable_check"]
    assert checks[-1]["valid"] is True


# -- AC: kill-switch ----------------------------------------------------------
def test_salvage_kill_switch_skips_rescue(monkeypatch, stub_openai, tmp_path, events):
    stub_state["script"] = [_plan_step(), _work_step(), _salvage_step("hello"), _review_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path), salvage="0")

    # no salvage phase; the run proceeds work -> commit with the check results
    assert _phase_starts(events) == ["plan", "work", "commit"]
    assert not (tmp_path / "hello.txt").exists()
    checks = [e for e in events if e.get("event") == "deliverable_check"]
    assert checks and checks[-1]["exists"] is False


# -- no trigger when the deliverable is fine ----------------------------------
def test_no_salvage_when_deliverable_exists(monkeypatch, stub_openai, tmp_path, events):
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    stub_state["script"] = [_plan_step(), _work_step(), _salvage_step("hello"), _review_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))

    assert _phase_starts(events) == ["plan", "work", "commit"]
    checks = [e for e in events if e.get("event") == "deliverable_check"]
    assert checks and checks[-1]["valid"] is True
    assert not any(e.get("event") == "salvage_persist" for e in events)


# -- spec resolution ----------------------------------------------------------
def test_spec_falls_back_to_work_deliverable(
    monkeypatch, stub_openai, tmp_path, events
):
    """No artifact_spec in the plan: WorkResult.deliverable carries the path."""
    plan = _plan_step()
    del plan["tool_call"]["arguments"]["artifact_spec"]
    stub_state["script"] = [_plan_step(), _work_step("answer.txt"), _salvage_step("42"), _review_step()]
    stub_state["script"][0] = plan
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))

    assert _phase_starts(events) == ["plan", "work", "salvage", "commit"]
    assert (tmp_path / "answer.txt").read_text(encoding="utf-8") == "42"


def test_unknown_path_skips_gate(monkeypatch, stub_openai, tmp_path, events):
    """Neither the plan nor the work names a path: the gate stays silent."""
    plan = _plan_step()
    del plan["tool_call"]["arguments"]["artifact_spec"]
    work = _work_step(deliverable="")
    stub_state["script"] = [plan, work, _review_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))

    assert _phase_starts(events) == ["plan", "work", "commit"]
    assert not any(e.get("event") == "deliverable_check" for e in events)


# -- phase unit tests ----------------------------------------------------------
def test_salvage_phase_is_write_only_fresh_and_typed():
    from shlepa_agent.config import load_config
    from shlepa_agent.outputs import SalvageResult
    from shlepa_agent.phases import get_phase

    cfg = load_config()
    phase = get_phase("salvage")
    assert phase.id == "salvage"
    assert phase.output_type is SalvageResult
    assert phase.terminal is False
    assert phase.tools(cfg) == ["write"]
    assert phase.limits(cfg).time == 30.0
