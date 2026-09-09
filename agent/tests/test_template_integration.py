"""Integration: the block template end-to-end through the stub OpenAI server.

Covers the t3 acceptance criteria on the 4-phase pipeline: the system
message carries base.md content, per-tool notes and the task text (constant
for the run), the plan user message carries the phase instructions, and the
commit request carries the commit text plus the resumed history.
"""

import asyncio

from stub_server import stub_state


def _run(
    monkeypatch, stub_openai, tmp_path, task="Create hello.txt with the exact content hello",
    agent_cfg=None,
):
    from shlepa_agent.runner import run_prompt

    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))
    return asyncio.run(run_prompt(task, agent_cfg=agent_cfg))


def test_plan_request_uses_template(monkeypatch, stub_openai, tmp_path):
    stub_state["script"] = [
        {
            "tool_call": {
                "name": "final_result",
                "arguments": {
                    "goal": "write hello.txt with the content hello",
                    "findings": "",
                    "steps": ["write the file"],
                },
            }
        },
        {
            "tool_call": {
                "name": "final_result",
                "arguments": {
                    "summary": "wrote hello.txt",
                    "findings": "",
                    "deliverable": "hello.txt",
                    "confidence": 1.0,
                },
            }
        },
        {
            "tool_call": {
                "name": "final_result",
                "arguments": {
                    "status": "ok",
                    "verdict": "done",
                    "artifact": "hello.txt",
                    "checks": ["re-read -> matches"],
                    "notes": "wrote hello.txt",
                },
            }
        },
    ]
    _run(monkeypatch, stub_openai, tmp_path)
    first = stub_state["bodies"][0]
    messages = first["messages"]
    system = messages[0]["content"]
    user = messages[1]["content"]
    # system message: base.md content + per-tool notes
    assert "expert autonomous cybersecurity agent" in system
    assert "FORMAT DISCIPLINE" in system
    assert "AVAILABLE TOOLS" in system
    # v6: the plan surface is read-only — recon/search instead of bash/write
    for tool in ("read", "recon", "search"):
        assert tool in system, tool
    # the task text renders into the system message (constant for the run)
    assert "Create hello.txt with the exact content hello" in system
    # first user message: plan phase instructions, advisory limits, output
    # schema — but NOT the task text (it is in the system message)
    assert "PHASE INSTRUCTIONS" in user
    assert "PLAN PHASE" in user
    assert "Create hello.txt with the exact content hello" not in user
    assert "ADDITIONAL CONTEXT" in user  # plan limits are rendered
    assert "OUTPUT FORMAT" in user  # the final_result schema
    assert "NO NOTES" not in user and "NOTES\n" not in user  # empty note block dropped
    # reserved empty blocks render nothing
    # the plan instructions mention the block name in prose — check header + content
    assert "RESULTS OF PREVIOUS PHASES\nwork phase" not in user


def test_review_relay_request_carries_relay_text_and_work_history(
    monkeypatch, stub_openai, tmp_path
):
    """The relay request (v6-rewrite) carries the relay prompt (review.md)
    plus the resumed WORK transcript: the work user message and the work
    final_result call are part of the relay conversation."""
    from stub_server import reset_stub_state

    reset_stub_state()
    stub_state["script"] = [
        {
            "tool_call": {  # the plan request (typed PlanResult)
                "name": "final_result",
                "arguments": {
                    "goal": "write /app/hello.txt",
                    "steps": ["echo hello > /app/hello.txt"],
                },
            }
        },
        {"tool_call": {"name": "bash", "arguments": {"command": "echo ok"}}},  # work req 1
        {
            "tool_call": {  # work req 2 (typed WorkResult)
                "name": "final_result",
                "arguments": {
                    "summary": "wrote hello.txt",
                    "findings": "",
                    "deliverable": "/app/hello.txt",
                    "confidence": 1.0,
                },
            }
        },
        {
            "tool_call": {  # the relay request (typed ReviewResult)
                "name": "final_result",
                "arguments": {
                    "summary": "wrote hello.txt",
                    "done": True,
                    "problems": [],
                    "hints_next": [],
                },
            }
        },
        # cycle 2: the relay ends the run's interesting part; these steps
        # replay a clean second cycle so the run exits "done".
        {
            "tool_call": {  # plan cycle 2
                "name": "final_result",
                "arguments": {
                    "goal": "write /app/hello.txt",
                    "steps": ["echo hello > /app/hello.txt"],
                },
            }
        },
        {
            "tool_call": {  # work cycle 2 (typed WorkResult)
                "name": "final_result",
                "arguments": {
                    "summary": "wrote hello.txt",
                    "findings": "",
                    "deliverable": "/app/hello.txt",
                    "confidence": 1.0,
                },
            }
        },
    ]
    # phases are bounded by time, not by request counts — the plan phase
    # ends with its typed PlanResult. The work phase makes a tool call first
    # so its conversation (prompt + tool call) survives trim_history into the
    # relay request.
    _run(monkeypatch, stub_openai, tmp_path)
    bodies = stub_state["bodies"]
    assert len(bodies) == 6, (
        f"expected plan + work x2 + relay + plan + work, got {len(bodies)}"
    )
    # the relay is the 4th request (0-based index 3)
    messages = bodies[3]["messages"]
    last_user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
    # relay text (review.md) in the relay's last user message
    assert "REVIEW PHASE (relay)" in last_user
    assert "PHASE INSTRUCTIONS" in last_user
    # resumed history: the work user message is still in the request
    assert any(
        "WORK PHASE" in (m.get("content") or "")
        for m in messages
        if m["role"] == "user" and m is not messages[-1]
    )
    # the final_result call from the work run is part of the resumed history
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in messages)
