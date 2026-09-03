"""w2-5: the REPAIR route — bounded artifact-only repair after a
repair_scope='local' review verdict.

Covers: the edit tool's REPAIR scope (artifact-only, one mutation), and
the harness re-check driving the exit (pass -> done, fail -> new
plan/work cycle) via stub-model pipeline runs.
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

[phases.commit]
tools = ["read", "search"]
requests = 20
time = 45.0
reasoning_effort = "low"
max_retries = 0

[phases.repair]
tools = ["read", "search", "edit"]
requests = 3
time = 20.0
max_retries = 0

[phases.salvage]
tools = ["write"]
requests = 5
time = 30.0
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


def _review_step(**extra):
    args = {
        "status": "partial",
        "verdict": "done",
        "artifact": "out.json",
        "checks": ["keys: 'answer' missing"],
        "hints": [],
        "notes": "out.json is missing the answer key",
    }
    args.update(extra)
    return {"tool_call": {"name": "final_result", "arguments": args}}


def _phase_starts(events):
    return [
        e["id"] for e in events if e.get("event") == "phase" and e.get("start")
    ]


# -- AC: routing ---------------------------------------------------------------
def test_repair_routes_on_scope_local_and_passes(
    monkeypatch, stub_openai, tmp_path, events
):
    # The work phase left a broken (but present) file: the salvage gate
    # stays off (the file is not missing/empty), VERIFY flags the failing
    # keys check with repair_scope=local, REPAIR edits the file once, and
    # the harness re-check drives the exit.
    (tmp_path / "out.json").write_text('{"x": 1}', encoding="utf-8")
    stub_state["script"] = [
        _plan_step(),
        _work_step(),
        _review_step(repair_scope="local"),
        {
            "tool_call": {
                "name": "edit",
                "arguments": {
                    "path": "out.json",
                    "edits": [
                        {
                            "oldText": '{"x": 1}',
                            "newText": '{"answer": 42, "x": 1}',
                        }
                    ],
                },
            }
        },
        {"final": "Fixed the keys check."},
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))
    status = next(
        e["status"] for e in events if e.get("event") == "agent_done" and "status" in e
    )

    assert _phase_starts(events) == ["plan", "work", "commit", "repair"]
    assert status == "done"
    # the harness re-check passed -> done; the file carries the fix
    assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8")) == {
        "answer": 42,
        "x": 1,
    }
    done = [e for e in events if e.get("event") == "repair_done"]
    assert done and done[0]["passed"] is True


def test_repair_fail_starts_new_cycle(
    monkeypatch, stub_openai, tmp_path, events
):
    # REPAIR did not fix the check: the harness re-check fails and the run
    # starts a new plan/work cycle (no time condition — the failed strict
    # check is the only trigger).
    (tmp_path / "out.json").write_text('{"x": 1}', encoding="utf-8")
    stub_state["script"] = [
        _plan_step(),
        _work_step(),
        _review_step(repair_scope="local"),
        {"final": "the fix is not obvious from the packet"},  # no edit
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))

    done = [e for e in events if e.get("event") == "repair_done"]
    assert done and done[0]["passed"] is False
    cycles = [
        e
        for e in events
        if e.get("event") == "cycle" and e.get("reason") == "repair_failed"
    ]
    assert cycles, "expected a repair_failed cycle"
    starts = _phase_starts(events)
    # repair -> plan: a new cycle started
    assert starts.index("repair") < starts.index("plan", starts.index("repair"))


# -- AC: edit scope -------------------------------------------------------------
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


# -- schema ----------------------------------------------------------------------
def test_review_result_repair_scope_schema():
    from shlepa_agent.outputs import ReviewResult

    r = ReviewResult(status="ok", verdict="done", artifact="x")
    assert r.repair_scope == "none"  # backward-compatible default
    for value in ("none", "local", "needs_next_round"):
        assert ReviewResult(
            status="ok", verdict="done", artifact="x", repair_scope=value
        ).repair_scope == value
    with pytest.raises(ValueError):
        ReviewResult(status="ok", verdict="done", artifact="x", repair_scope="all")
