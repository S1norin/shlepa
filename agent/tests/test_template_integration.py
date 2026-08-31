"""Integration: the block template end-to-end through the stub OpenAI server.

Covers the t3 acceptance criteria on the 4-phase pipeline: the system
message carries base.md content, per-tool notes and the task text (constant
for the run), the plan user message carries the phase instructions, and the
commit request carries the commit text plus the resumed history.
"""

import asyncio

from stub_server import FINAL_ANSWER, stub_state


def _run(monkeypatch, stub_openai, tmp_path, task="Create hello.txt with the exact content hello", agent_cfg=None):
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
                    "decision": "commit",
                },
            }
        },
        {
            "tool_call": {
                "name": "final_result",
                "arguments": {
                    "status": "ok",
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
    for tool in ("read", "write", "edit", "bash"):
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
    assert "RESULTS OF PREVIOUS PHASES" not in user


def test_commit_request_carries_commit_text_and_history(monkeypatch, stub_openai, tmp_path):
    from stub_server import reset_stub_state

    reset_stub_state()
    stub_state["script"] = [
        {
            "tool_call": {  # the plan request (typed PlanResult)
                "name": "final_result",
                "arguments": {
                    "goal": "write /app/hello.txt",
                    "steps": ["echo hello > /app/hello.txt"],
                    "decision": "work",
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
                    "decision": "commit",
                },
            }
        },
        {
            "tool_call": {  # the commit request (typed CommitResult)
                "name": "final_result",
                "arguments": {
                    "status": "ok",
                    "artifact": "/app/hello.txt",
                    "checks": ["re-read -> matches"],
                    "notes": "wrote hello.txt",
                },
            }
        },
    ]
    # v5: phases are bounded by time, not by request counts — the plan phase
    # ends with its typed PlanResult. The work phase makes a tool call first
    # so its conversation (prompt + tool call) survives trim_history into the
    # commit request.
    _run(monkeypatch, stub_openai, tmp_path)
    bodies = stub_state["bodies"]
    assert len(bodies) == 4, (
        f"expected plan + work x2 + commit, got {len(bodies)}"
    )
    messages = bodies[-1]["messages"]
    last_user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
    # commit text (commit.md) in the final user message
    assert "COMMIT PHASE" in last_user
    assert "PHASE INSTRUCTIONS" in last_user
    # resumed history: the work user message is still in the request
    assert any(
        "WORK PHASE" in (m.get("content") or "")
        for m in messages
        if m["role"] == "user" and m is not messages[-1]
    )
    # the final_result call from the work run is part of the resumed history
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in messages)
