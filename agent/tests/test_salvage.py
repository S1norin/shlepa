"""v6-rewrite: the SALVAGE route is DISABLED (kept for re-enable).

The w2-3 write-only rescue (write-only phase, harness-persisted
final_result.body fallback, SHLEPA_SALVAGE=0 kill-switch) is no longer
routed by the hard-cycle pipeline: there is no salvage gate between WORK
and the next cycle. The phase file, prompt, config section and the runner
helpers (``_salvage_needed`` / ``_persist_salvage_body``) stay on disk for
a later re-enable; they are disabled via ``[tool_policy].disabled``.

This file pins the new behavior (the pipeline never routes to salvage or
commit) and keeps the harness-persist helper as a direct unit test so the
re-enable stays cheap.
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
    """Test config with the [phases.salvage] section (the production
    shape) — even disabled phases keep their config sections on disk."""
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

[phases.review]
requests = 20
time = 45.0
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


def _relay_step(done: bool = False):
    return {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "summary": "attempted hello.txt",
                "done": done,
                "problems": [] if done else ["file not written"],
                "hints_next": [] if done else ["write the file"],
            },
        }
    }


def _phase_starts(events):
    return [
        e["id"]
        for e in events
        if e.get("event") == "phase" and e.get("start")
    ]


# -- AC: the pipeline never routes salvage (or commit) -----------------------
def test_pipeline_never_routes_salvage_or_commit(
    monkeypatch, stub_openai, tmp_path, events
):
    """WORK leaves the deliverable missing: no salvage rescue, no commit
    verifier — the run is exactly plan, work, relay, plan, work and ends
    with the (empty) work outcome."""
    stub_state["script"] = [
        _plan_step(),
        _work_step(),
        _relay_step(),
        _plan_step(),
        _work_step(),
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))

    assert _phase_starts(events) == ["plan", "work", "review", "plan", "work"]
    assert not (tmp_path / "hello.txt").exists()
    # the mechanical check still ran after each work (the gate is kept;
    # only the routing behind it is gone)
    checks = [e for e in events if e.get("event") == "deliverable_check"]
    assert len(checks) == 2
    assert all(c["exists"] is False for c in checks)
    assert not any(e.get("event") == "salvage_persist" for e in events)
    done = [e for e in events if e.get("event") == "agent_done"]
    assert done and done[-1]["status"] == "done"


def test_salvage_kill_switch_has_no_routing_effect(
    monkeypatch, stub_openai, tmp_path, events
):
    """SHLEPA_SALVAGE=0 no longer changes anything (no route exists):
    identical phase sequence with and without the kill-switch."""
    stub_state["script"] = [
        _plan_step(),
        _work_step(),
        _relay_step(),
        _plan_step(),
        _work_step(),
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path), salvage="0")
    assert _phase_starts(events) == ["plan", "work", "review", "plan", "work"]
    assert not (tmp_path / "hello.txt").exists()


# -- unit tests (kept for a later re-enable) ---------------------------------
def test_persist_salvage_body_persists_when_file_absent(tmp_path, events):
    """The harness-persist helper still works standalone: it writes the
    salvage final_result.body only when the model never wrote the file."""
    from shlepa_agent.config import load_config
    from shlepa_agent.outputs import SalvageResult
    from shlepa_agent.phases.base import PhaseResult, RunState
    from shlepa_agent.runner import _persist_salvage_body
    from shlepa_agent.tools.base import AgentDeps

    deps = AgentDeps(workdir=tmp_path, cfg=load_config(), clock=lambda: 0.0)
    st = RunState(task="t", deps=deps, model=None)
    st.deliverable_spec = {
        "kind": "file",
        "path": "hello.txt",
        "format": "text",
        "keys": [],
        "expected_content": "hello",
    }
    st.results["salvage"] = PhaseResult(
        status="done",
        summary="salvaged",
        output=SalvageResult(body="hello", path=""),
    )
    _persist_salvage_body(st)
    f = tmp_path / "hello.txt"
    assert f.is_file()
    assert f.read_text(encoding="utf-8") == "hello"
    assert any(e.get("event") == "salvage_persist" for e in events)

    # a file the model itself wrote wins: the body is only the fallback
    f.write_text("model-wrote-this", encoding="utf-8")
    _persist_salvage_body(st)
    assert f.read_text(encoding="utf-8") == "model-wrote-this"


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
    # disabled in the shipped tool policy (never routed)
    assert cfg.tool_policy.is_disabled("salvage")
