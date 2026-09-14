"""v6-rewrite: best-at-exit snapshots are DISABLED (kept for re-enable).

The w2-9 harness functions (``_maybe_snapshot_best`` / ``_restore_best_on_exit``)
stay on disk but are no longer called by the pipeline: the file state after
the LAST work is what gets scored. The unit tests below still pin the
functions; the e2e test pins the disabled behavior (no restoration).

This module also hosts the shared stub-pipeline helpers (``_cfg``,
``_plan_step``, ``_work_step``, ``_relay_step``) used by several test files.
"""

import asyncio
import json
import logging

import pytest

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
[tools.recon]
enabled = true

[phases.plan]
tools = ["read", "recon"]
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

[phases.commit]
tools = ["read"]
requests = 20
time = 45.0
reasoning_effort = "low"
max_retries = 0

[phases.repair]
tools = ["read", "edit"]
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
                "goal": "write json",
                "steps": ["write file"],
                "findings": "",
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
                "status": "ok",
                "summary": "wrote out.json",
                "deliverable": "out.json",
                "findings": "",
            },
        }
    }


def _relay_step(done: bool = False):
    """A typed ReviewResult step for the v6-rewrite review relay."""
    return {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "summary": "wrote out.json",
                "done": done,
                "problems": [] if done else ["answer key unverified"],
                "hints_next": [] if done else ["verify the answer key"],
            },
        }
    }


def test_round2_overwrite_is_not_restored(
    monkeypatch, stub_openai, tmp_path, events
):
    """v6-rewrite: best-at-exit is disabled — round 2 overwrites the file
    with an invalid one and the run ends 'done' with round 2's content on
    disk (no artifact_restored event, no snapshot taken)."""
    stub_state["script"] = [
        _plan_step(),
        {
            "tool_call": {
                "name": "write",
                "arguments": {"path": "out.json", "text": '{"answer": 42}'},
            }
        },
        _work_step(),
        _relay_step(done=False),
        _plan_step(),
        {
            "tool_call": {
                "name": "edit",
                "arguments": {
                    "path": "out.json",
                    "edits": [
                        {"oldText": '{"answer": 42}', "newText": '{"x": 1}'}
                    ],
                },
            }
        },
        _work_step(),
    ]
    _run(monkeypatch, stub_openai, tmp_path, _cfg(tmp_path))

    f = tmp_path / "out.json"
    assert f.read_text() == '{"x": 1}', (
        "v6-rewrite: no best-at-exit restoration — the last work wins"
    )
    assert not any(e.get("event") == "artifact_restored" for e in events)
    done = [e for e in events if e.get("event") == "agent_done"]
    assert done and done[-1]["status"] == "done"


# -- unit tests -------------------------------------------------------------

def _state(tmp_path, valid: bool, file_text: str | None):
    from shlepa_agent.config import load_config
    from shlepa_agent.phases.base import RunState
    from shlepa_agent.tools.base import AgentDeps

    if file_text is not None:
        (tmp_path / "out.json").write_text(file_text, encoding="utf-8")
    deps = AgentDeps(workdir=tmp_path, cfg=load_config(), clock=lambda: 0.0)
    st = RunState(task="t", deps=deps, model=None)
    st.deliverable_spec = {
        "kind": "file",
        "path": "out.json",
        "format": "json",
        "keys": ["answer"],
    }
    st.deliverable_check = {"valid": valid}
    return st


def test_maybe_snapshot_only_when_valid(tmp_path):
    from shlepa_agent.runner import _maybe_snapshot_best

    st = _state(tmp_path, valid=False, file_text='{"x": 1}')
    _maybe_snapshot_best(st)
    assert st.best_snapshot is None
    (tmp_path / "out.json").write_text('{"answer": 42}', encoding="utf-8")
    st.deliverable_check = {"valid": True}
    _maybe_snapshot_best(st)
    assert st.best_snapshot is not None
    assert st.best_snapshot["content"] == '{"answer": 42}'
    assert len(st.best_snapshot["sha256"]) == 64


def test_restore_keeps_valid_file(tmp_path, events):
    from shlepa_agent.runner import _maybe_snapshot_best, _restore_best_on_exit

    st = _state(tmp_path, valid=True, file_text='{"answer": 42}')
    _maybe_snapshot_best(st)
    _restore_best_on_exit(st)
    assert (tmp_path / "out.json").read_text() == '{"answer": 42}'
    assert not any(e.get("event") == "artifact_restored" for e in events)
