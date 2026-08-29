"""Integration: the v2 block template end-to-end through the stub OpenAI server.

Covers the t3 acceptance criteria: the explore request's first user message
contains the rendered task, the system message carries base.md content and
per-tool notes, and the commit request carries the commit text plus the
resumed history.
"""

import asyncio

from stub_server import FINAL_ANSWER, stub_state


def _run(monkeypatch, stub_openai, tmp_path, task="Create hello.txt with the exact content hello"):
    from shlepa_agent.core import run_prompt

    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))
    return asyncio.run(run_prompt(task))


def test_explore_request_uses_template(monkeypatch, stub_openai, tmp_path):
    _run(monkeypatch, stub_openai, tmp_path)
    first = stub_state["bodies"][0]
    messages = first["messages"]
    system = messages[0]["content"]
    user = messages[1]["content"]
    # system message: base.md content + per-tool notes
    assert "expert autonomous cybersecurity agent" in system
    assert "FORMAT DISCIPLINE" in system
    assert "AVAILABLE TOOLS" in system
    assert "bash" in system and "write_file" in system and "apply_diff" in system
    # first user message: rendered task + phase instructions
    assert "Create hello.txt with the exact content hello" in user
    assert "PHASE INSTRUCTIONS" in user
    assert "NO NOTES" not in user and "NOTES\n" not in user  # empty note block dropped
    # reserved blocks render nothing while empty
    assert "ADDITIONAL CONTEXT" not in user
    assert "RESULTS OF PREVIOUS PHASES" not in user
    assert "OUTPUT FORMAT" not in user


def test_commit_request_carries_commit_text_and_history(monkeypatch, stub_openai, tmp_path):
    from stub_server import reset_stub_state

    reset_stub_state()
    stub_state["script"] = [
        {"tool_call": {"name": "bash", "arguments": {"command": "echo ok"}}},
        {"tool_call": {"name": "bash", "arguments": {"command": "echo ok"}}},
        {"final": FINAL_ANSWER},  # the commit request
    ]
    # request limit 2 -> the third explore request raises UsageLimitExceeded,
    # routing the run to the commit phase.
    monkeypatch.setenv("AGENT_REQUEST_LIMIT", "2")
    _run(monkeypatch, stub_openai, tmp_path)
    bodies = stub_state["bodies"]
    assert len(bodies) == 3, f"expected explore x2 + commit x1, got {len(bodies)}"
    messages = bodies[2]["messages"]
    last_user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
    # commit text (commit.md) in the final user message
    assert "BUDGET EXHAUSTED" in last_user
    assert "PHASE INSTRUCTIONS" in last_user
    # resumed history: the rendered explore user message is still in the request
    assert any(
        "Create hello.txt with the exact content hello" in (m.get("content") or "")
        for m in messages
        if m["role"] == "user" and m is not messages[-1]
    )
    # tool calls from the explore run are part of the resumed history
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in messages)
