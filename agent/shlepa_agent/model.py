"""Budgeted OpenAI model wrapper.

TrackedModel wraps OpenAIChatModel with:
- per-request usage logging (``usage`` events),
- soft/hard wall-clock budgeting (the soft budget raises BudgetExceeded,
  routing the run into the commit phase),
- a per-request wall-clock cap on stream consumption (_WallCappedStream),
- one retry for transient network errors,
- context-overflow detection mapped to BudgetExceeded.

All budget values come from the v2 agent config ([budget] section).
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any

from openai import APIConnectionError, APIStatusError
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from shlepa_agent.config import AgentConfig
from shlepa_agent.log import _log_event

CONTEXT_ERROR_MARKERS = (
    "maximum context",
    "context length",
    "too long",
    "exceed",
    "reduce the length",
    "length limit",
)


class BudgetExceeded(Exception):
    """Raised inside the model when the agent must stop exploring and commit."""


def _looks_like_context_error(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in CONTEXT_ERROR_MARKERS)


class _WallCappedStream:
    """Proxy around a StreamedResponse enforcing a wall-clock deadline on consumption.

    pydantic-ai consumes the stream outside of our control: the request_timeout
    in _open_stream only covers opening the stream (up to the first bytes). A
    single request that keeps generating forever (runaway loop) or a server
    that stops sending chunks mid-stream (zombie) would otherwise hang the
    agent until harbor kills the container. This proxy makes every __anext__
    respect the shared deadline (open -> last chunk) and raises ModelAPIError
    when it is exceeded, which routes the run into the commit phase.
    """

    def __init__(self, inner: Any, deadline: float, model_name: str, wall: float) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_deadline", deadline)
        object.__setattr__(self, "_model_name", model_name)
        object.__setattr__(self, "_wall", wall)
        object.__setattr__(self, "_iter", None)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_inner"), name)

    def __aiter__(self) -> "_WallCappedStream":
        if object.__getattribute__(self, "_iter") is None:
            object.__setattr__(self, "_iter", object.__getattribute__(self, "_inner").__aiter__())
        return self

    async def __anext__(self) -> Any:
        self.__aiter__()
        remaining = self._deadline - time.monotonic()
        msg = (
            f"request wall exceeded: single request ran longer than "
            f"{self._wall:.0f}s (open -> last chunk)"
        )
        if remaining <= 0:
            raise ModelAPIError(self._model_name, msg)
        try:
            return await asyncio.wait_for(
                object.__getattribute__(self, "_iter").__anext__(), timeout=remaining
            )
        except asyncio.TimeoutError:
            raise ModelAPIError(self._model_name, msg) from None


class TrackedModel(OpenAIChatModel):
    """OpenAIChatModel with wall-clock/token budgeting and per-request usage logs."""

    def __init__(self, model_name: str, provider: OpenAIProvider, agent_cfg: AgentConfig):
        super().__init__(model_name, provider=provider)
        self.cfg = agent_cfg.budget
        self.t0 = time.monotonic()
        self.last_messages: list[Any] = []
        self.enable_soft_check = True
        self._pending_stream: Any = None
        self._request_no = 0
        self._cum_input = 0
        self._cum_output = 0

    # -- helpers ----------------------------------------------------------
    def _capped_settings(self, model_settings: Any) -> dict:
        """Copy of model_settings with a per-request max_tokens cap applied."""
        ms = dict(model_settings or {})
        if self.cfg.max_tokens and not ms.get("max_tokens"):
            ms["max_tokens"] = self.cfg.max_tokens
        return ms

    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    def _soft_expired(self) -> bool:
        return self.enable_soft_check and self.elapsed() > self.cfg.soft_time

    def _hard_expired(self) -> bool:
        return self.elapsed() > self.cfg.hard_time

    def log_pending_usage(self) -> None:
        """Log the usage of the previous (now-finalized) streamed response."""
        sr = self._pending_stream
        self._pending_stream = None
        if sr is None:
            return
        try:
            usage = sr.usage
        except Exception:
            usage = None
        if usage is None:
            return
        self._request_no += 1
        inp = int(usage.input_tokens or 0)
        out = int(usage.output_tokens or 0)
        self._cum_input += inp
        self._cum_output += out
        _log_event(
            "usage",
            request=self._request_no,
            input_tokens=inp,
            output_tokens=out,
            cumulative_input=self._cum_input,
            cumulative_output=self._cum_output,
            cumulative_total=self._cum_input + self._cum_output,
            elapsed_s=round(self.elapsed(), 1),
        )

    async def _open_stream(self, messages, model_settings, model_request_parameters, run_context):
        """Open the upstream stream, retrying transient network errors once.

        Returns (streamed_response, context_manager); the caller must close the CM.
        """
        cm: Any = None
        last_err: Exception | None = None
        for attempt in (1, 2):
            if self._hard_expired():
                raise BudgetExceeded(f"hard time limit {self.cfg.hard_time:.0f}s exceeded")
            if self._soft_expired():
                raise BudgetExceeded(
                    f"soft time limit {self.cfg.soft_time:.0f}s exceeded before request"
                )
            try:
                async with asyncio.timeout(self.cfg.request_timeout):
                    cm = super(TrackedModel, self).request_stream(
                        messages, model_settings, model_request_parameters, run_context
                    )
                    sr = await cm.__aenter__()
                return sr, cm
            except BudgetExceeded:
                raise
            except (TimeoutError, asyncio.TimeoutError) as e:
                last_err = e
            except APIConnectionError as e:
                last_err = e
            except APIStatusError as e:
                body = f"{e} {getattr(e, 'body', '')}"
                if _looks_like_context_error(body):
                    raise BudgetExceeded(f"model context limit: {str(e)[:200]}")
                if e.status_code < 500:
                    raise ModelAPIError(
                        self.model_name, f"model request failed ({e.status_code}): {str(e)[:300]}"
                    )
                last_err = e
            except Exception as e:
                if _looks_like_context_error(str(e)):
                    raise BudgetExceeded(f"model context limit: {str(e)[:200]}")
                last_err = e
            if cm is not None:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:
                    pass
                cm = None
            if attempt == 1:
                await asyncio.sleep(1.0)
        raise ModelAPIError(
            self.model_name, f"model request failed after retry: {str(last_err)[:300]}"
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
        self.log_pending_usage()
        self.last_messages = list(messages)
        model_settings = self._capped_settings(model_settings)
        sr, cm = await self._open_stream(
            messages, model_settings, model_request_parameters, run_context
        )
        self._pending_stream = sr
        # Consumption happens in pydantic-ai's drain loop, outside any timeout
        # we set in _open_stream; enforce the request wall around the stream.
        wall_deadline = time.monotonic() + self.cfg.request_wall
        try:
            yield _WallCappedStream(sr, wall_deadline, self.model_name, self.cfg.request_wall)
        finally:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass

    async def request(
        self,
        messages: list[Any],
        model_settings: Any,
        model_request_parameters: Any,
    ) -> Any:
        self.log_pending_usage()
        self.last_messages = list(messages)
        model_settings = self._capped_settings(model_settings)
        last_err: Exception | None = None
        for attempt in (1, 2):
            if self._hard_expired():
                raise BudgetExceeded(f"hard time limit {self.cfg.hard_time:.0f}s exceeded")
            if self._soft_expired():
                raise BudgetExceeded(
                    f"soft time limit {self.cfg.soft_time:.0f}s exceeded before request"
                )
            try:
                async with asyncio.timeout(self.cfg.request_timeout):
                    return await super(TrackedModel, self).request(
                        messages, model_settings, model_request_parameters
                    )
            except BudgetExceeded:
                raise
            except (TimeoutError, asyncio.TimeoutError) as e:
                last_err = e
            except APIConnectionError as e:
                last_err = e
            except APIStatusError as e:
                body = f"{e} {getattr(e, 'body', '')}"
                if _looks_like_context_error(body):
                    raise BudgetExceeded(f"model context limit: {str(e)[:200]}")
                if e.status_code < 500:
                    raise ModelAPIError(
                        self.model_name, f"model request failed ({e.status_code}): {str(e)[:300]}"
                    )
                last_err = e
            except Exception as e:
                if _looks_like_context_error(str(e)):
                    raise BudgetExceeded(f"model context limit: {str(e)[:200]}")
                last_err = e
            if attempt == 1:
                await asyncio.sleep(1.0)
        raise ModelAPIError(
            self.model_name, f"model request failed after retry: {str(last_err)[:300]}"
        )
