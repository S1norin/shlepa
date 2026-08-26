"""Integration test: baseline agent loop against a stub OpenAI-compatible server."""

import asyncio

from stub_server import FINAL_ANSWER, stub_state


def test_baseline_completes_against_stub(monkeypatch, stub_openai, tmp_path):
    from shlepa_agent.core import run_prompt

    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))

    output = asyncio.run(run_prompt("Create hello.txt with the exact content hello"))

    assert output == FINAL_ANSWER
    body = stub_state["last_body"]
    assert body["model"] == "stub-model"
    system_prompt = body["messages"][0]["content"]
    assert "non-interactive coding agent" in system_prompt
