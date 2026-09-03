"""w1-5: PartialHandoff typed model + deterministic LAST_TOOLS extraction.

The plan-timeout hand-off is a typed pydantic model (weak answers must not
crash the run) plus a deterministic tail of the plan conversation (last N
tool calls with capped args/results) that the harness appends to the work
prompt regardless of the model's answer quality.
"""
from __future__ import annotations

import pytest

from shlepa_agent.outputs import PartialHandoff


# -- PartialHandoff ---------------------------------------------------------

def test_partial_handoff_full_validation():
    h = PartialHandoff.model_validate(
        {
            "objective": "write /app/out.json with keys a,b",
            "findings": ["port 8080 serves the API (recon url)"],
            "files_seen": ["/app/task.txt", "/app/server.py"],
            "hypotheses": ["flag is in the /admin endpoint"],
            "failed_paths": ["curl /flag -> 404"],
            "next_action": "probe /admin with the recon output",
            "deliverable_path_if_known": "/app/out.json",
        }
    )
    assert h.findings[0].startswith("port 8080")
    assert h.files_seen == ["/app/task.txt", "/app/server.py"]
    assert h.deliverable_path_if_known == "/app/out.json"


def test_partial_handoff_missing_fields_default():
    # every field has a default: an empty or partial answer still validates
    h = PartialHandoff.model_validate({})
    assert h.objective == ""
    assert h.findings == []
    assert h.files_seen == []
    assert h.hypotheses == []
    assert h.failed_paths == []
    assert h.next_action == ""
    assert h.deliverable_path_if_known == ""


def test_partial_handoff_malformed_fields_do_not_crash():
    # a stray scalar in a list field is coerced, not rejected
    h = PartialHandoff.model_validate(
        {
            "findings": "found the flag",
            "files_seen": None,
            "hypotheses": ["one"],
        }
    )
    assert h.findings == ["found the flag"]
    assert h.files_seen == []
    assert h.hypotheses == ["one"]


def test_partial_handoff_json_roundtrip():
    h = PartialHandoff(objective="goal", findings=["f1"], next_action="act")
    restored = PartialHandoff.model_validate_json(h.model_dump_json())
    assert restored == h


# -- LAST_TOOLS extraction ---------------------------------------------------

def _messages(triples):
    """Build a synthetic conversation: list of (tool, args, result) triples."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        ToolCallPart,
        ToolReturnPart,
    )

    msgs = []
    for tool, args, result in triples:
        call = ToolCallPart(tool_name=tool, args=args)
        msgs.append(ModelRequest(parts=[call]))
        if result is not None:
            msgs.append(ModelResponse(parts=[ToolReturnPart(tool_name=tool, content=result)]))
    return msgs


def test_last_tools_returns_the_last_n_in_order():
    from shlepa_agent.state import extract_last_tools

    triples = [(f"t{i}", f"a{i}", f"r{i}") for i in range(10)]
    entries = extract_last_tools(_messages(triples), n=6)
    assert [e["tool"] for e in entries] == [f"t{i}" for i in range(4, 10)]
    assert entries[0]["args"] == "a4"
    assert entries[0]["result"] == "r4"


def test_last_tools_empty_conversation_and_n_zero(monkeypatch):
    from shlepa_agent import state

    assert state.extract_last_tools([], n=6) == []
    assert state.extract_last_tools(None, n=6) == []
    assert state.extract_last_tools(_messages([("t0", "a", "r")]), n=0) == []
    monkeypatch.setenv("SHLEPA_LAST_TOOLS_N", "2")
    assert state.last_tools_n() == 2
    monkeypatch.setenv("SHLEPA_LAST_TOOLS_N", "garbage")
    assert state.last_tools_n() == state.LAST_TOOLS_N


def test_last_tools_caps_args_and_results():
    from shlepa_agent.state import (
        LAST_TOOLS_ARGS_CAP,
        LAST_TOOLS_RESULT_CAP,
        extract_last_tools,
    )

    entries = extract_last_tools(
        _messages([("bash", "x" * 1000, "y" * 1000)]), n=6
    )
    assert len(entries[0]["args"]) <= LAST_TOOLS_ARGS_CAP + 10
    assert entries[0]["args"].startswith("x" * 100)
    assert entries[0]["args"].endswith("[...]")
    assert len(entries[0]["result"]) <= LAST_TOOLS_RESULT_CAP + 10
    assert entries[0]["result"].startswith("y" * 100)
    assert entries[0]["result"].endswith("[...]")


def test_last_tools_excludes_final_result_and_handles_missing_returns():
    from shlepa_agent.state import extract_last_tools

    msgs = _messages([("read", "/app/task.txt", "task body")])
    # a final_result call (the typed output tool) is not a hand-off tool
    from pydantic_ai.messages import ModelRequest, ToolCallPart

    msgs.append(
        ModelRequest(
            parts=[ToolCallPart(tool_name="final_result", args='{"goal": "g"}')]
        )
    )
    # a call without a visible result keeps an empty result slot
    msgs.append(ModelRequest(parts=[ToolCallPart(tool_name="bash", args="ls")]))

    entries = extract_last_tools(msgs, n=6)
    assert [e["tool"] for e in entries] == ["read", "bash"]
    assert entries[0]["result"] == "task body"
    assert entries[1]["result"] == ""


def test_last_tools_dict_args_are_serialized():
    from shlepa_agent.state import extract_last_tools

    entries = extract_last_tools(
        _messages([("bash", {"command": "ls -la"}, "total 0")]), n=6
    )
    assert '"command": "ls -la"' in entries[0]["args"]
    assert entries[0]["result"] == "total 0"


def test_last_tools_env_size_override(monkeypatch):
    from shlepa_agent import state

    monkeypatch.setenv("SHLEPA_LAST_TOOLS_N", "3")
    triples = [(f"t{i}", "a", "r") for i in range(8)]
    entries = state.extract_last_tools(_messages(triples))  # n from env
    assert [e["tool"] for e in entries] == ["t5", "t6", "t7"]


# -- LAST_TOOLS rendering ----------------------------------------------------

def test_render_last_tools_block():
    from shlepa_agent.state import render_last_tools

    text = render_last_tools(
        [
            {"tool": "bash", "args": 'curl localhost:8080/admin', "result": "200 OK"},
            {"tool": "read", "args": "path='/app/x'", "result": ""},
        ]
    )
    assert "LAST TOOLS" in text
    assert "bash(curl localhost:8080/admin)" in text
    assert "-> 200 OK" in text
    assert "read(path='/app/x')" in text
    assert render_last_tools([]) == ""
