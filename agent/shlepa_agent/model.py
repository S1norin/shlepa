"""Tracked OpenAI model wrapper (v5).

TrackedModel wraps OpenAIChatModel with:
- per-request usage logging (``usage`` events) — tokens are counted for
  telemetry / tie-break analysis only, never limited,
- per-operation time bounds (the only bounds in the agent): the per-request
  open timeout (``[budget].request_timeout``) and the per-request
  wall-clock cap on stream consumption (``budget.LLM_WALL``, open -> last
  chunk),
- one retry for transient network errors,
- context-overflow detection mapped to BudgetExceeded (a normal hand-off,
  never a retryable error).

There is NO task time limit T, NO global hard stop and NO request-start
gate: the agent works in cycles until the review verdict is "done" or the
container is killed at the task's own limit.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any

from openai import APIConnectionError, APIStatusError
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from shlepa_agent.budget import LLM_WALL
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

#: Output-cap rejection markers: a 400 whose body matches one of these
#: (and is not a context/prompt-length error) means the endpoint refused
#: the requested max_tokens output budget. Lower bound for the adaptive
#: cap: below 2048 tokens a deliverable is rarely writable in one request.
MAX_TOKENS_ERROR_MARKERS = (
    "max_tokens",
    "max tokens",
    "max_output",
    "max output",
    "output tokens",
    "output length",
    "completion tokens",
    "maximum number of tokens",
    "requested more",
)


#: Lowest max_tokens the adaptive logic will fall back to.
MIN_MAX_TOKENS = 2048

#: The exact user prompt of the preflight probe (see TrackedModel.preflight).
PREFLIGHT_PROBE_TEXT = "Reply with the single word: ok"


class BudgetExceeded(Exception):
    """Raised inside the model on a context-overflow error. The runner
    treats it as a normal hand-off (never retryable)."""


class _MaxTokensRejected(Exception):
    """Internal signal: the endpoint refused the requested max_tokens.

    Carries the reduced cap the caller should try next."""

    def __init__(self, reduced_to: int) -> None:
        super().__init__(f"max_tokens rejected, retry with {reduced_to}")
        self.reduced_to = reduced_to


def _looks_like_context_error(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in CONTEXT_ERROR_MARKERS)


def _looks_like_max_tokens_error(status_code: int, text: str) -> bool:
    """True for a 400 that rejects the requested output budget.

    Must be checked BEFORE the context markers: cap messages often say
    'exceeds the maximum', which the context markers would swallow.
    Context/prompt/input framing disqualifies (that is a real context
    overflow, not an output-cap rejection).
    """
    if status_code != 400:
        return False
    low = text.lower()
    if any(word in low for word in ("context", "prompt", "input")):
        return False
    return any(marker in low for marker in MAX_TOKENS_ERROR_MARKERS)


class _WallCappedStream:
    """Proxy around a StreamedResponse enforcing a wall-clock deadline on consumption.

    pydantic-ai consumes the stream outside of our control: the request_timeout
    in _open_stream only covers opening the stream (up to the first bytes). A
    single request that keeps generating forever (runaway loop) or a server
    that stops sending chunks mid-stream (zombie) would otherwise hang the
    agent until the container is killed. This proxy makes every __anext__
    respect the shared deadline (open -> last chunk) and raises ModelAPIError
    when it is exceeded, which hands the phase off to the review phase.
    """

    def __init__(
        self,
        inner: Any,
        deadline: float,
        model_name: str,
        wall: float,
        on_error: Any = None,
    ) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_deadline", deadline)
        object.__setattr__(self, "_model_name", model_name)
        object.__setattr__(self, "_wall", wall)
        object.__setattr__(self, "_iter", None)
        # w3-5: streaming HTTP errors (429/5xx) surface here, not in
        # _open_stream — the SDK sends the request lazily on the first
        # chunk. on_error is TrackedModel.note_endpoint_failure.
        object.__setattr__(self, "_on_error", on_error)

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
        except APIStatusError as e:
            # w3-5: count the terminal failure (429/402/5xx) before it
            # propagates to the phase (one count per request: the error
            # ends the stream, so this fires once).
            on_error = object.__getattribute__(self, "_on_error")
            if on_error is not None:
                try:
                    on_error(e.status_code)
                except Exception:  # pragma: no cover - defensive
                    pass
            raise


class TrackedModel(OpenAIChatModel):
    """OpenAIChatModel with per-request time caps and usage logs.

    Tokens are counted and logged only (tie-break analysis); they are never
    limited. Every operation is bounded by time (per-request open timeout +
    wall cap); the run itself is bounded by the phase caps (runner) and the
    review verdict.
    """

    def __init__(
        self,
        model_name: str,
        provider: OpenAIProvider,
        agent_cfg: AgentConfig,
    ):
        super().__init__(model_name, provider=provider)
        self.cfg = agent_cfg.budget
        self.request_timeout = self.cfg.request_timeout
        self.llm_wall = LLM_WALL
        self.t0 = time.monotonic()
        self.last_messages: list[Any] = []
        self._pending_stream: Any = None
        self._request_no = 0
        self._cum_input = 0
        self._cum_output = 0
        self._cum_cache_read = 0
        self._cum_cache_write = 0
        # w3-5: consecutive terminal endpoint failures (429/402/5xx storm)
        # — the only observable proxy for the invisible external token cap.
        self._endpoint_fails = 0
        #: Id of the phase currently running (set/rotated by the runner);
        #: usage events are tagged with it for per-phase token attribution.
        self.current_phase: str | None = None
        #: Discovered output budget of the endpoint (set by preflight or by
        #: the adaptive 400 handler). None = undiscovered (use cfg.max_tokens);
        #: 0 = the endpoint rejected every explicit cap but accepts a request
        #: with no max_tokens (its own default applies); >0 = send that value.
        #: Contests expose an unknown OpenAI-compatible endpoint; a
        #: max_tokens larger than its output cap rejects every request
        #: with 400, which otherwise scores 0 on every task.
        self.effective_max_tokens: int | None = None

    #: Terminal endpoint failure codes (w3-5): 402 (token/payment cap),
    #: 429 (rate limit) and any 5xx. 400/401/403/404 do not count.
    TERMINAL_ENDPOINT_STATUSES = (402, 429)

    # -- w3-5 endpoint-failure tracking -------------------------------------
    def _is_terminal_endpoint_status(self, status_code: int) -> bool:
        return (
            status_code in self.TERMINAL_ENDPOINT_STATUSES or status_code >= 500
        )

    def note_endpoint_failure(self, status_code: int) -> None:
        """Record one terminal endpoint failure (429/402/5xx); non-terminal
        codes are ignored. One request counts at most once."""
        if not self._is_terminal_endpoint_status(status_code):
            return
        self._endpoint_fails += 1
        _log_event(
            "endpoint_error",
            status=status_code,
            consecutive=self._endpoint_fails,
            limit=self.cfg.endpoint_fail_limit,
        )

    def note_endpoint_success(self) -> None:
        """A normally opened request breaks the failure streak."""
        if self._endpoint_fails:
            _log_event("endpoint_recovered", after=self._endpoint_fails)
            self._endpoint_fails = 0

    @property
    def endpoint_failure_count(self) -> int:
        return self._endpoint_fails

    @property
    def endpoint_stalled(self) -> bool:
        """True once >= endpoint_fail_limit consecutive terminal endpoint
        failures were observed (the runner finalizes the run then)."""
        return self._endpoint_fails >= self.cfg.endpoint_fail_limit

    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    # -- endpoint preflight -------------------------------------------------
    async def preflight(self) -> bool:
        """Probe the model endpoint with one minimal streaming request.

        The contest exposes an unknown OpenAI-compatible endpoint. This
        preflight (a) verifies the endpoint/model/key work at all, and
        (b) picks a request shape the endpoint accepts. Two shapes are
        probed with minimal streaming requests:

        1. No-cap (no max_tokens field). Earlier checkpoints in this
           contest scored only when max_tokens was absent, so a plain
           request is probed first.
        2. Cap ladder (configured cap, halving down to MIN_MAX_TOKENS on
           cap rejections). A capped request bounds the model's output
           (fast, predictable timing), so an ACCEPTED cap wins over no-cap.

        A connection-level failure on the first probe aborts (the endpoint
        is unreachable); an HTTP error means the endpoint is up and simply
        rejects that shape, so probing continues. 0 means "send no
        max_tokens". Never raises: on failure it logs the full status +
        body and the run proceeds with the configured default (the failure
        may be transient).
        """
        no_cap_ok = False
        try:
            await self._probe_stream({})
            no_cap_ok = True
        except _MaxTokensRejected:
            pass  # endpoint wants an explicit cap; the ladder finds it
        except Exception as e:  # noqa: BLE001 - must never break the run
            if getattr(e, "status_code", None) is None:
                body = f"{e} {getattr(e, 'body', '')}"
                _log_event(
                    "endpoint_preflight",
                    ok=False,
                    max_tokens=0,
                    detail=str(e)[:500],
                    body=body[:500],
                )
                return False  # connection-level: endpoint is down
            # HTTP error: endpoint is up but rejects the no-cap shape;
            # the cap ladder below may still find an accepted shape.

        cap_ok: int | None = None
        for cap in self._cap_ladder():
            try:
                await self._probe_stream({"max_tokens": cap})
                cap_ok = cap
                break
            except _MaxTokensRejected:
                continue  # next lower cap
            except Exception:  # noqa: BLE001 - endpoint rejects max_tokens
                break

        if cap_ok is not None:
            self.effective_max_tokens = cap_ok
            _log_event(
                "endpoint_preflight",
                ok=True,
                max_tokens=cap_ok,
                default_cap=self.cfg.max_tokens,
            )
            return True
        if no_cap_ok:
            self.effective_max_tokens = 0
            _log_event(
                "endpoint_preflight",
                ok=True,
                max_tokens=0,
                default_cap=self.cfg.max_tokens,
            )
            return True
        _log_event(
            "endpoint_preflight",
            ok=False,
            detail=f"no-cap and caps down to {MIN_MAX_TOKENS} all rejected",
        )
        return False

    def _cap_ladder(self) -> list[int]:
        """max_tokens probes, highest accepted budget first."""
        caps: list[int] = []
        for cap in (self.cfg.max_tokens, 8192, 4096, MIN_MAX_TOKENS):
            if cap and cap not in caps:
                caps.append(cap)
        return caps

    async def _probe_stream(self, model_settings: dict) -> None:
        """One minimal streaming completion through the production path.

        Raises _MaxTokensRejected when the endpoint refuses the requested
        output budget (the handler has already recorded the reduced cap);
        any other failure propagates to preflight's logging.
        """
        from pydantic_ai.messages import ModelRequest, UserPromptPart
        from pydantic_ai.models import ModelRequestParameters

        # request_stream wants ModelMessage objects (ModelRequest/ModelResponse),
        # not raw prompt tuples -- raw tuples hit an assert_never in _map_messages.
        request = ModelRequest(
            parts=[UserPromptPart(content=PREFLIGHT_PROBE_TEXT)]
        )
        cm = super(TrackedModel, self).request_stream(
            [request],
            model_settings,
            ModelRequestParameters(),  # no tools; prepare_request reads .native_tools
            None,
        )
        try:
            async with asyncio.timeout(self.request_timeout):
                sr = await cm.__aenter__()
                # The SDK sends the request lazily on the first chunk.
                async for _ in sr:
                    pass
        except ModelHTTPError as e:
            body = f"{e} {getattr(e, 'body', '')}"
            if _looks_like_max_tokens_error(e.status_code, body):
                raise _MaxTokensRejected(
                    max(MIN_MAX_TOKENS, int(model_settings.get("max_tokens") or 0) // 2)
                ) from e
            raise
        except APIStatusError as e:
            body = f"{e} {getattr(e, 'body', '')}"
            if _looks_like_max_tokens_error(e.status_code, body):
                raise _MaxTokensRejected(
                    max(MIN_MAX_TOKENS, int(model_settings.get("max_tokens") or 0) // 2)
                ) from e
            raise
        finally:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:  # pragma: no cover - defensive
                pass

    # -- helpers ----------------------------------------------------------
    def _capped_settings(self, model_settings: Any) -> dict:
        """Copy of model_settings with a per-request max_tokens cap applied.

        A discovered cap of 0 means "send no max_tokens at all": the
        endpoint rejected every explicit cap and its own default output
        budget applies."""
        ms = dict(model_settings or {})
        if self.effective_max_tokens is None:
            cap = self.cfg.max_tokens
        else:
            cap = self.effective_max_tokens
        if cap and not ms.get("max_tokens"):
            ms["max_tokens"] = cap
        return ms

    def _try_reduce_max_tokens(
        self, status_code: int, body: str, model_settings: dict
    ) -> bool:
        """On an output-cap 400, halve the cap and prepare a retry.

        Returns True when the cap was reduced (the caller then treats the
        failure as retryable instead of terminal); False otherwise."""
        current = int(model_settings.get("max_tokens") or 0)
        if (
            current > MIN_MAX_TOKENS
            and _looks_like_max_tokens_error(status_code, body)
        ):
            new = max(MIN_MAX_TOKENS, current // 2)
            model_settings["max_tokens"] = new
            self.effective_max_tokens = new
            _log_event(
                "endpoint_max_tokens",
                previous=current,
                reduced_to=new,
                body=body[:300],
            )
            return True
        return False

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
        # Prompt-cache accounting (0 when the endpoint does not report it):
        # pydantic-ai Usage carries the counts, older shapes do not.
        cache_read = int(getattr(usage, "cache_read_tokens", 0) or 0)
        cache_write = int(getattr(usage, "cache_write_tokens", 0) or 0)
        details = getattr(usage, "details", None) or {}
        self._cum_input += inp
        self._cum_output += out
        self._cum_cache_read += cache_read
        self._cum_cache_write += cache_write
        fields = dict(
            request=self._request_no,
            input_tokens=inp,
            output_tokens=out,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            cumulative_input=self._cum_input,
            cumulative_output=self._cum_output,
            cumulative_total=self._cum_input + self._cum_output,
            cumulative_cache_read=self._cum_cache_read,
            cumulative_cache_write=self._cum_cache_write,
            elapsed_s=round(self.elapsed(), 1),
        )
        # Reasoning tokens are only present when the endpoint reports them
        # (via completion_tokens_details.reasoning_tokens); absent otherwise.
        reasoning = details.get("reasoning_tokens")
        if reasoning is not None:
            fields["reasoning_tokens"] = int(reasoning)
        # Phase id (set by the runner before each phase run); absent when no
        # phase is set so legacy consumers see an unchanged event shape.
        if self.current_phase is not None:
            fields["phase"] = self.current_phase
        _log_event("usage", **fields)

    async def _open_stream(self, messages, model_settings, model_request_parameters, run_context):
        """Open the upstream stream, retrying transient network errors once.

        Returns (streamed_response, context_manager); the caller must close the CM.
        """
        cm: Any = None
        last_err: Exception | None = None
        last_status: int | None = None
        for attempt in (1, 2):
            _log_event("llm_request", attempt=attempt, phase=self.current_phase)
            try:
                async with asyncio.timeout(self.request_timeout):
                    cm = super(TrackedModel, self).request_stream(
                        messages, model_settings, model_request_parameters, run_context
                    )
                    sr = await cm.__aenter__()
                return sr, cm
            except BudgetExceeded:
                raise
            except (TimeoutError, asyncio.TimeoutError) as e:
                _log_event("llm_error", error_type=type(e).__name__, phase=self.current_phase)
                last_err = e
            except APIConnectionError as e:
                _log_event("llm_error", error_type=type(e).__name__, phase=self.current_phase)
                last_err = e
            except ModelHTTPError as e:
                # pydantic-ai wraps provider HTTP errors; terminal codes
                # (w3-5) are counted and never retried, non-terminal 4xx
                # keep the one-retry behavior.
                body = f"{e} {getattr(e, 'body', '')}"
                if self._try_reduce_max_tokens(e.status_code, body, model_settings):
                    last_err = e  # retry with the reduced cap
                elif _looks_like_context_error(body):
                    raise BudgetExceeded(f"model context limit: {str(e)[:200]}")
                elif self._is_terminal_endpoint_status(e.status_code):
                    self.note_endpoint_failure(e.status_code)
                    raise ModelAPIError(
                        self.model_name,
                        f"model request failed ({e.status_code}): {str(e)[:300]}",
                    )
                else:
                    last_err = e
            except APIStatusError as e:
                _log_event("llm_error", error_type=type(e).__name__, phase=self.current_phase)
                body = f"{e} {getattr(e, 'body', '')}"
                if self._try_reduce_max_tokens(e.status_code, body, model_settings):
                    last_err = e  # retry with the reduced cap
                elif _looks_like_context_error(body):
                    raise BudgetExceeded(f"model context limit: {str(e)[:200]}")
                elif self._is_terminal_endpoint_status(e.status_code):
                    self.note_endpoint_failure(e.status_code)
                    raise ModelAPIError(
                        self.model_name, f"model request failed ({e.status_code}): {str(e)[:300]}"
                    )
                else:
                    last_err = e
                    last_status = e.status_code
            except Exception as e:
                _log_event("llm_error", error_type=type(e).__name__, phase=self.current_phase)
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
                _log_event("llm_retry", phase=self.current_phase)
                await asyncio.sleep(1.0)
        if last_status is not None:
            self.note_endpoint_failure(last_status)
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
        self.note_endpoint_success()
        self._pending_stream = sr
        # Consumption happens in pydantic-ai's drain loop, outside any timeout
        # we set in _open_stream; enforce the request wall around the stream.
        wall = self.llm_wall
        wall_deadline = time.monotonic() + wall
        try:
            yield _WallCappedStream(
                sr, wall_deadline, self.model_name, wall, on_error=self.note_endpoint_failure
            )
        except Exception as exc:
            _log_event("llm_error", error_type=type(exc).__name__, phase=self.current_phase)
            raise
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
        last_status: int | None = None
        for attempt in (1, 2):
            _log_event("llm_request", attempt=attempt, phase=self.current_phase)
            try:
                async with asyncio.timeout(self.request_timeout):
                    response = await super(TrackedModel, self).request(
                        messages, model_settings, model_request_parameters
                    )
                    self.note_endpoint_success()
                    self._pending_stream = response
                    self.log_pending_usage()
                    return response
            except BudgetExceeded:
                raise
            except (TimeoutError, asyncio.TimeoutError) as e:
                _log_event("llm_error", error_type=type(e).__name__, phase=self.current_phase)
                last_err = e
            except APIConnectionError as e:
                _log_event("llm_error", error_type=type(e).__name__, phase=self.current_phase)
                last_err = e
            except ModelHTTPError as e:
                # pydantic-ai wraps provider HTTP errors; terminal codes
                # (w3-5) are counted and never retried.
                body = f"{e} {getattr(e, 'body', '')}"
                if self._try_reduce_max_tokens(e.status_code, body, model_settings):
                    last_err = e  # retry with the reduced cap
                elif _looks_like_context_error(body):
                    raise BudgetExceeded(f"model context limit: {str(e)[:200]}")
                elif self._is_terminal_endpoint_status(e.status_code):
                    self.note_endpoint_failure(e.status_code)
                    raise ModelAPIError(
                        self.model_name,
                        f"model request failed ({e.status_code}): {str(e)[:300]}",
                    )
                else:
                    last_err = e
            except APIStatusError as e:
                _log_event("llm_error", error_type=type(e).__name__, phase=self.current_phase)
                body = f"{e} {getattr(e, 'body', '')}"
                if self._try_reduce_max_tokens(e.status_code, body, model_settings):
                    last_err = e  # retry with the reduced cap
                elif _looks_like_context_error(body):
                    raise BudgetExceeded(f"model context limit: {str(e)[:200]}")
                elif self._is_terminal_endpoint_status(e.status_code):
                    self.note_endpoint_failure(e.status_code)
                    raise ModelAPIError(
                        self.model_name, f"model request failed ({e.status_code}): {str(e)[:300]}"
                    )
                else:
                    last_err = e
                    last_status = e.status_code
            except Exception as e:
                _log_event("llm_error", error_type=type(e).__name__, phase=self.current_phase)
                if _looks_like_context_error(str(e)):
                    raise BudgetExceeded(f"model context limit: {str(e)[:200]}")
                last_err = e
            if attempt == 1:
                _log_event("llm_retry", phase=self.current_phase)
                await asyncio.sleep(1.0)
        if last_status is not None:
            self.note_endpoint_failure(last_status)
        raise ModelAPIError(
            self.model_name, f"model request failed after retry: {str(last_err)[:300]}"
        )
