"""Integration test: the agent loop (v2 runner) against a stub OpenAI server."""

import asyncio

from stub_server import FINAL_ANSWER, PIPELINE_SCRIPT, stub_state


def test_baseline_completes_against_stub(monkeypatch, stub_openai, tmp_path):
    from shlepa_agent.runner import run_prompt

    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))

    stub_state["script"] = list(PIPELINE_SCRIPT)
    output = asyncio.run(run_prompt("Create hello.txt with the exact content hello"))

    assert output == FINAL_ANSWER
    body = stub_state["last_body"]
    assert body["model"] == "stub-model"
    system_prompt = body["messages"][0]["content"]
    assert "expert autonomous cybersecurity agent" in system_prompt
