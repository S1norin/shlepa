"""v6-rewrite: the REPAIR route is DISABLED (kept for re-enable).

The w2-5 bounded artifact-only repair (repair_scope='local' verdict ->
REPAIR phase, harness re-check driving the exit) is no longer routed by
the hard-cycle pipeline: there is no verifier verdict, so there is no
repair trigger. The phase file, prompt, config section and the edit
tool's REPAIR scope (artifact-only, one mutation) stay on disk for a
later re-enable; the phase is disabled via ``[tool_policy].disabled``.

This file pins the new behavior (the pipeline never routes to repair)
and keeps the edit-tool REPAIR-scope mechanics as direct unit tests.
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


def _run(monkeypatch, stub_openai, tmp_path, agent_cfg, task="create out.json"):
    from shlepa_agent import runner

    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))
    monkeypatch.delenv("SHLEPA_SALVAGE", raising=False)
    monkeypatch.delenv("SHLEPA_REVIEW_CTX", raising=False)
    return asyncio.run(runner.run_prompt(task, agent_cfg=agent_cfg))


def _cfg(tmp_path):
    p = tmp_path / "cfg.toml"
    p.write_text(
        """
[agent]
temp = 0.6
send_temp = true
entry = "plan"
emergency = "emergency"
max_steps = 16

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

[phases.review]
requests = 20
time = 45.0
reasoning_effort = "low"
max_retries = 0

[phases.repair]
tools = ["read", "edit"]
requests = 3
time = 20.0
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
                "goal": "write out.json with the answer key",
                "findings": "",
                "steps": ["write the file"],
                "artifact_spec": {
                    "kind": "file",
                    "path": "out.json",
                    "format": "json",
                    "keys": ["answer"],
                },
            },
        }
    }


def _work_step():
    return {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "summary": "wrote out.json",
                "findings": "",
                "deliverable": "out.json",
                "confidence": 0.9,
            },
        }
    }


def _relay_step(done: bool = False):
    return {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "summary": "wrote out.json but the answer key is missing",
                "done": done,
                "problems": [] if done else ["keys: 'answer' missing"],
                "hints_next": [] if done else ["add the answer key"],
            },
        }
    }


def _phase_starts(events):
    return [
        e["id"] for e in events if e.get("event") == "phase" and e.get("start")
    ]


# -- AC: the pipeline never routes repair -------------------------------------
def test_pipeline_never_routes_repair(monkeypatch, stub_openai, tmp_path, events):
    """A broken-but-present deliverable no longer triggers REPAIR: the
    relay distills the problem into the next cycle's context, and the
    run is exactly plan, work, relay, plan, work (no repair_done)."""
    (tmp_path / "out.json").write_text('{"x": 1}', encoding="utf-8")
    stub_state["script"] = [
        _plan_step(),
        _work_step(),
        _relay_step(done=False),
        _plan_step(),
        _work_step(),
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))

    assert _phase_starts(events) == ["plan", "work", "review", "plan", "work"]
    assert not any(e.get("event") == "repair_done" for e in events)
    # the mechanical check still ran after each work and still flagged
    # the missing key (the gate is kept; only the routing behind it is gone)
    checks = [e for e in events if e.get("event") == "deliverable_check"]
    assert len(checks) == 2
    assert all(not c["valid"] for c in checks)
    done = [e for e in events if e.get("event") == "agent_done"]
    assert done and done[-1]["status"] == "done"
    # the relay's problems are carried into the cycle-2 PLAN request
    bodies = [json.dumps(b) for b in stub_state["bodies"]]
    assert any("keys: 'answer' missing" in b for b in bodies)


# -- AC: edit scope (kept for a later re-enable) -------------------------------
def _edit_ctx(tmp_path):
    from shlepa_agent.config import load_config
    from shlepa_agent.tools.base import AgentDeps, RepairScope

    cfg = load_config()
    scope = RepairScope(path=(tmp_path / "out.json").resolve())
    deps = AgentDeps(
        workdir=tmp_path,
        cfg=cfg,
        clock=lambda: 0.0,
        repair_scope=scope,
    )
    ctx = type("C", (), {})()
    ctx.deps = deps
    return ctx, scope


def test_repair_scope_rejects_non_deliverable_path(tmp_path):
    from shlepa_agent.tools.edit import edit

    (tmp_path / "out.json").write_text('{"x": 1}', encoding="utf-8")
    other = tmp_path / "other.txt"
    other.write_text("do not touch", encoding="utf-8")
    ctx, _ = _edit_ctx(tmp_path)
    result = asyncio.run(
        edit(ctx, path="other.txt", edits=[{"oldText": "touch", "newText": "TOUCH"}])
    )
    assert "REPAIR scope" in result
    assert other.read_text(encoding="utf-8") == "do not touch"


def test_repair_scope_rejects_second_mutation(tmp_path):
    from shlepa_agent.tools.edit import edit

    (tmp_path / "out.json").write_text('{"x": 1}', encoding="utf-8")
    ctx, scope = _edit_ctx(tmp_path)
    ok = asyncio.run(
        edit(
            ctx,
            path="out.json",
            edits=[{"oldText": '{"x": 1}', "newText": '{"answer": 42, "x": 1}'}],
        )
    )
    assert "FAILED" not in ok
    assert scope.mutations_used == 1
    again = asyncio.run(
        edit(ctx, path="out.json", edits=[{"oldText": "42", "newText": "43"}])
    )
    assert "budget exhausted" in again
    assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))[
        "answer"
    ] == 42


def test_repair_phase_stays_registered_and_disabled():
    from shlepa_agent.config import load_config
    from shlepa_agent.phases import get_phase

    cfg = load_config()
    phase = get_phase("repair")
    assert phase.id == "repair"
    assert phase.terminal is False
    assert phase.tools(cfg) == ["read", "edit"]
    assert phase.limits(cfg).time == 20.0
    # disabled in the shipped tool policy (never routed)
    assert cfg.tool_policy.is_disabled("repair")
