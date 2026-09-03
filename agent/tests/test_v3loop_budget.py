"""BudgetedModel (v3 loop regime): the depleting soft/hard budget gates.

v3 semantics: the elapsed wall time is checked against the ``[v3loop]``
soft and hard budgets BEFORE every LLM request; a breach raises
BudgetExceeded (the pipeline hands off to the terminal commit phase). The
commit phase disables the soft check so it can spend the remaining hard
window; the hard check always stays active. The per-request wall uses
``[v3loop].request_wall`` (240s), not the cycles regime's fixed 180s.
"""

import asyncio
import time
from contextlib import asynccontextmanager

import pytest

import shlepa_agent.model as model_mod


def _make_model(tmp_path, soft=500.0, hard=585.0, wall=240.0):
    from pydantic_ai.providers.openai import OpenAIProvider

    from shlepa_agent.config import load_config
    from shlepa_agent.v3loop import BudgetedModel

    p = tmp_path / "cfg.toml"
    p.write_text(
        f"""\
[agent]
temp = 0.1

[v3loop]
soft_time = {soft}
hard_time = {hard}
request_wall = {wall}

[phases.plan]
tools = ["bash"]
requests = 5
""",
        encoding="utf-8",
    )
    return BudgetedModel(
        "stub-model",
        OpenAIProvider(base_url="http://localhost:1/v1", api_key="k"),
        load_config(p),
    )


def _age(model, seconds):
    """Move the model's clock `seconds` into the past (deterministic breach)."""
    model.t0 = time.monotonic() - seconds


def test_v3loop_budget_values_from_config(tmp_path):
    model = _make_model(tmp_path)
    assert model.soft_time == 500.0
    assert model.hard_time == 585.0
    assert model.request_wall == 240.0
    # The stream wall uses the v3 value, not the cycles LLM_WALL (180).
    from shlepa_agent.budget import LLM_WALL

    assert model.llm_wall == 240.0
    assert model.llm_wall != LLM_WALL
    assert model.enable_soft_check is True


def test_under_budget_request_succeeds(tmp_path, monkeypatch):
    model = _make_model(tmp_path)
    async def fake_super(self, messages, ms, params):
        return "ok"

    monkeypatch.setattr(model_mod.OpenAIChatModel, "request", fake_super)
    assert asyncio.run(model.request([], {}, None)) == "ok"


def test_soft_breach_raises_before_request(tmp_path, monkeypatch):
    model = _make_model(tmp_path, soft=1.0, hard=100.0)
    _age(model, 2.0)  # past soft, well under hard
    calls: list[int] = []

    async def fake_super(self, messages, ms, params):
        calls.append(1)
        return "ok"

    monkeypatch.setattr(model_mod.OpenAIChatModel, "request", fake_super)
    with pytest.raises(model_mod.BudgetExceeded, match="soft time limit"):
        asyncio.run(model.request([], {}, None))
    assert calls == []  # the gate fires before the upstream call


def test_soft_disabled_allows_request_under_hard(tmp_path, monkeypatch):
    """Commit phase: soft check off, hard not yet due -> the request runs."""
    model = _make_model(tmp_path, soft=1.0, hard=100.0)
    model.enable_soft_check = False
    _age(model, 2.0)

    async def fake_super(self, messages, ms, params):
        return "ok"

    monkeypatch.setattr(model_mod.OpenAIChatModel, "request", fake_super)
    assert asyncio.run(model.request([], {}, None)) == "ok"


def test_hard_breach_raises_even_with_soft_disabled(tmp_path, monkeypatch):
    model = _make_model(tmp_path, soft=1.0, hard=10.0)
    model.enable_soft_check = False
    _age(model, 20.0)
    calls: list[int] = []

    async def fake_super(self, messages, ms, params):
        calls.append(1)
        return "ok"

    monkeypatch.setattr(model_mod.OpenAIChatModel, "request", fake_super)
    with pytest.raises(model_mod.BudgetExceeded, match="hard time limit"):
        asyncio.run(model.request([], {}, None))
    assert calls == []


def test_stream_path_gated_the_same_way(tmp_path, monkeypatch):
    """The agent always streams; the pre-request gate must cover it too."""
    model = _make_model(tmp_path, soft=1.0, hard=10.0)
    _age(model, 2.0)
    calls: list[int] = []

    @asynccontextmanager
    async def fake_super_stream(self, messages, ms, params, run_context=None):
        calls.append(1)
        yield "stream"

    monkeypatch.setattr(model_mod.OpenAIChatModel, "request_stream", fake_super_stream)

    async def consume():
        async with model.request_stream([], {}, None) as _stream:
            pass

    with pytest.raises(model_mod.BudgetExceeded, match="soft time limit"):
        asyncio.run(consume())
    assert calls == []
