"""v3 loop regime: the budgeted main phase -> terminal commit.

The control flow of the registered v3 agent (MLflow model version 3, run
ee78c24c) on top of the v5 modular toolset/config/model machinery:

- ONE open main phase: the full tool loop (the arm's toolset, free text —
  no typed output), bounded NOT by a per-phase cap but by the depleting
  ``[v3loop]`` budget: soft/hard wall-clock checks before every LLM
  request (:class:`BudgetedModel`), plus the request-count and total-token
  budgets via pydantic-ai ``UsageLimits``.
- On a budget breach (``BudgetExceeded`` / ``UsageLimitExceeded``) or a
  persistent model error the run hands off to the TERMINAL commit phase:
  one short window (``commit_time_cap``, capped at the remaining hard
  window) to write the deliverable from the information already gathered.
  A normal main finish does NOT trigger the commit (v3 parity: the main
  run already wrote the deliverable); a non-budget error ends the run
  without a commit.

The loop axis is orthogonal to the toolset arms (``toolsets.py``): the v3
regime runs with any arm. Selected via ``[agent].loop`` / ``SHLEPA_LOOP``;
the default regime is the v5 cycles pipeline (``runner.py``).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from pydantic_ai.providers.openai import OpenAIProvider

from shlepa_agent.config import AgentConfig
from shlepa_agent.model import BudgetExceeded, TrackedModel


class BudgetedModel(TrackedModel):
    """TrackedModel with the v3 depleting budget (soft/hard wall gates).

    v3 semantics: before every LLM request the elapsed wall time is
    checked against the ``[v3loop]`` soft/hard budgets; a breach raises
    :class:`~shlepa_agent.model.BudgetExceeded`, which the pipeline hands
    off to the terminal commit phase. The commit phase disables the soft
    check (``enable_soft_check = False``) so it can spend the remaining
    hard window; the hard check stays active in both phases. The
    request-count and total-token budgets are enforced by pydantic-ai
    ``UsageLimits`` in the pipeline (v3 parity), and the per-request wall
    uses ``[v3loop].request_wall`` (240s) instead of the cycles regime's
    fixed 180s ``LLM_WALL``.
    """

    def __init__(self, model_name: str, provider: OpenAIProvider, agent_cfg: AgentConfig):
        super().__init__(model_name, provider, agent_cfg)
        v3 = agent_cfg.v3loop
        self.soft_time = v3.soft_time
        self.hard_time = v3.hard_time
        self.request_wall = v3.request_wall
        # The stream wall cap uses the v3 value (request_wall), not the
        # cycles regime's fixed LLM_WALL.
        self.llm_wall = v3.request_wall
        #: Soft-budget gate; the commit phase disables it (the hard check
        #: stays active so the commit cannot run past the hard window).
        self.enable_soft_check = True

    # -- budget gates (v3 _open_stream semantics) -------------------------
    def _soft_expired(self) -> bool:
        return self.enable_soft_check and self.elapsed() > self.soft_time

    def _hard_expired(self) -> bool:
        return self.elapsed() > self.hard_time

    def _budget_check(self) -> None:
        """Pre-request gate: raises BudgetExceeded on a soft/hard breach."""
        if self._hard_expired():
            raise BudgetExceeded(f"hard time limit {self.hard_time:.0f}s exceeded")
        if self._soft_expired():
            raise BudgetExceeded(
                f"soft time limit {self.soft_time:.0f}s exceeded before request"
            )

    # -- overrides ----------------------------------------------------------
    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[Any],
        model_settings: Any,
        model_request_parameters: Any,
        run_context: Any = None,
    ):
        self._budget_check()
        async with super().request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as stream:
            yield stream

    async def request(
        self,
        messages: list[Any],
        model_settings: Any,
        model_request_parameters: Any,
    ) -> Any:
        self._budget_check()
        return await super().request(messages, model_settings, model_request_parameters)
