"""Shlepa agent (v1): budgeted main phase + commit phase.

Ported from the 2026-08-24 submission (registered as shlepa:3 in the MLflow
model registry), replacing the plain vendored upstream baseline with the v1
design:

- Main phase: stream a pydantic-ai agent run with a request limit and a soft
  total-token budget. The budget/limit breach raises UsageLimitExceeded
  (pydantic-ai) or BudgetExceeded (our model), which triggers the commit phase.
- Commit phase: resume the SAME conversation (trimmed message history) with a
  short "write the deliverable now" prompt under a strict time cap.
- TrackedModel(OpenAIChatModel): per-request usage logging, wall-clock budget
  checks, one retry for transient network errors, context-overflow detection.
- Never crash: any unexpected failure is logged as agent_error and the process
  exits 0 (a crash scores 0 anyway; a partial deliverable may score 1).

Telemetry is opt-in via the ``instrument`` flag (see ``__main__.py``); this
module never imports the otel SDK stack.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APIStatusError
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelAPIError, UsageLimitExceeded
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.run import AgentRunResultEvent
from pydantic_ai.usage import UsageLimits

MAX_LOG_VALUE_CHARS = 16000
LOGGER = logging.getLogger("shlepa-agent")
# NOTE: "token" on its own is too broad (would redact usage fields like input_tokens).
SECRET_FIELD_MARKERS = ("api_key", "apikey", "secret", "password", "auth_token", "access_token")

COMMIT_PROMPT = (
    "\u26a0\ufe0f BUDGET EXHAUSTED. Stop exploring. Write the final deliverable NOW to the exact "
    "path with the exact format using only the information you already have. If the deliverable "
    "file already exists, verify it exactly once (re-read / jq / wc -l) and correct it if wrong. "
    "Then finish with one short line. Use only the tools needed to write and verify the file."
)

SYSTEM_PROMPT = """You are an expert autonomous cybersecurity agent. You work alone in an isolated
Linux container with no internet access. Task files live in the working directory (usually /app).
Always use absolute paths.

ENVIRONMENT
- Tools: bash (killed after 120 seconds), read_file, write_file (writes exact full content, adds
nothing, no trailing newline), append_file, apply_diff (unified diff).
- Start any server with nohup, &, then verify it responds.

PROTOCOL (follow strictly, in order)
1. Read the task. Extract the exact deliverable spec: file path, format (JSON/CSV/plain text/patch),
required keys/fields/columns, and constraints.
2. Do the minimum work needed. Explore only what is required.
3. Write the deliverable to the exact path in the exact format. Prefer write_file over bash
heredocs.
4. Verify mechanically: re-read the file; validate JSON with jq or python -c json.load; check line
counts with wc -l; compare required names, values, and order against the spec. Fix any mismatch.
5. Reply with one short line naming the deliverable path, then STOP. Never do extra work after
verification.

FORMAT DISCIPLINE
- Output nothing extra and nothing missing: only the required fields/lines, with exact names, in the
required order.
- Copy strings, hashes, timestamps, and commands verbatim from the source data. Never paraphrase,
reformat, or "improve" values.

CODE FIX TASKS
- Fix the root cause with the smallest correct change (e.g. parameterized queries instead of
string-built SQL).
- Keep the API surface unchanged: same function names, signatures, ports, endpoints.
- No new dependencies; use only the standard library or packages already present.
- Run the provided tests until green. Do not modify tests unless the task explicitly says to.

BUDGET
- Never run the same failing command more than twice; change strategy.
- If you receive a "BUDGET EXHAUSTED" message: stop exploring immediately, write the deliverable
now from the information you already have, verify it once, and finish with one line."""


class BudgetExceeded(Exception):
    """Raised inside the model when the agent must stop exploring and commit."""


@dataclass(frozen=True)
class Config:
    temp: float
    hard_time: float
    soft_time: float
    commit_time_cap: float
    request_limit: int
    commit_request_limit: int
    token_budget: int
    bash_timeout: float
    request_timeout: float
    request_wall: float
    max_tokens: int
    max_tool_output: int
    commit_reasoning_effort: str


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default) or default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def load_config() -> Config:
    return Config(
        temp=_env_float("AGENT_TEMP", 0.2),
        # Task agent timeout is 600s (closed set). Budgets stay under it with margin:
        # soft fire at ~500s, commit window up to 80s, process done by ~585s.
        hard_time=_env_float("AGENT_HARD_TIME", 585.0),
        soft_time=_env_float("AGENT_SOFT_TIME", 500.0),
        commit_time_cap=_env_float("AGENT_COMMIT_TIME_CAP", 80.0),
        request_limit=_env_int("AGENT_REQUEST_LIMIT", 90),
        commit_request_limit=_env_int("AGENT_COMMIT_REQUEST_LIMIT", 25),
        token_budget=_env_int("AGENT_TOKEN_BUDGET", 300000),
        bash_timeout=_env_float("AGENT_BASH_TIMEOUT", 120.0),
        request_timeout=_env_float("AGENT_REQUEST_TIMEOUT", 180.0),
        # Kill a single in-flight request if it runs this long (open -> last
        # chunk). Prevents one very slow generation (e.g. a long thinking
        # stream on a degraded server) from eating the whole budget and
        # leaving no commit window. Healthy requests finish in 10-120s.
        request_wall=_env_float("AGENT_REQUEST_WALL", 240.0),
        # Hard per-request output cap. Without it a single request can loop
        # for tens of thousands of tokens (observed: 45k in one turn) and eat
        # the whole trial before the commit phase can run.
        max_tokens=_env_int("AGENT_MAX_TOKENS", 16384),
        max_tool_output=_env_int("AGENT_MAX_TOOL_OUTPUT", 16000),
        # Commit run should act, not think: low reasoning effort keeps the
        # commit inside its (short) time window. Main run keeps the server
        # default (medium) so hard tasks still get real reasoning.
        commit_reasoning_effort=_env_str("AGENT_COMMIT_REASONING_EFFORT", "low"),
    )


@dataclass(frozen=True)
class LocalAgentDeps:
    workdir: Path
    bash_timeout: float
    max_tool_output: int


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [output truncated to {limit} chars]"


def _configure_logging() -> None:
    if LOGGER.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[shlepa-agent] %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


def _safe_log_value(key: str, value: Any) -> Any:
    if any(marker in key.lower() for marker in SECRET_FIELD_MARKERS):
        return "<redacted>"
    if isinstance(value, str):
        return _truncate(value, MAX_LOG_VALUE_CHARS)
    if isinstance(value, dict):
        return {str(k): _safe_log_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_log_value(key, item) for item in value]
    return value


def _log_event(event: str, **fields: Any) -> None:
    _configure_logging()
    payload = {"event": event}
    payload.update({key: _safe_log_value(key, value) for key, value in fields.items()})
    LOGGER.info(json.dumps(payload, ensure_ascii=False, default=str))


def _log_stream_event(event: Any) -> str | None:
    if isinstance(event, FunctionToolCallEvent):
        part = event.part
        fields = {"tool": part.tool_name}
        if isinstance(part.args, dict):
            fields.update(part.args)
        else:
            fields["args"] = part.args
        _log_event("llm_tool_call", **fields)
        return None

    if isinstance(event, FunctionToolResultEvent):
        result = getattr(event, "result", None) or getattr(event, "part", None)
        _log_event(
            "llm_tool_result",
            tool=getattr(result, "tool_name", None),
            result=getattr(result, "content", getattr(event, "content", None)),
        )
        return None

    if isinstance(event, AgentRunResultEvent):
        output = str(event.result.output)
        usage = getattr(event.result, "usage", None)
        if usage is not None:
            _log_event(
                "run_usage",
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                requests=getattr(usage, "requests", None),
                tool_calls=getattr(usage, "tool_calls", None),
            )
        _log_event("agent_done", output=output)
        return output

    return None


def _resolve_workdir() -> Path:
    # In the ACP image the agent cwd is /app; prefer it so task-relative paths work.
    app = Path("/app")
    if app.is_dir():
        return app
    raw = os.environ.get("LOCAL_AGENT_WORKDIR")
    if raw:
        return Path(raw).resolve()
    return Path.cwd().resolve()


def _resolve_path(path: str, workdir: Path) -> Path:
    if Path(path).is_absolute():
        return Path(path).resolve()
    return (workdir / path).resolve()


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    raise ValueError(f"Missing required environment variable: {name}")


def _resolve_model_name() -> str:
    model_name = os.environ.get("LOCAL_AGENT_MODEL") or os.environ.get("OPENAI_MODEL")
    if model_name:
        return model_name
    raise ValueError(
        "Missing required model name: set LOCAL_AGENT_MODEL (preferred) or OPENAI_MODEL"
    )


# ---------------------------------------------------------------------------
# Tracked model: budget checks, usage logging, one retry for transient errors
# ---------------------------------------------------------------------------

CONTEXT_ERROR_MARKERS = (
    "maximum context",
    "context length",
    "too long",
    "exceed",
    "reduce the length",
    "length limit",
)


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

    def __init__(self, model_name: str, provider: OpenAIProvider, cfg: Config):
        super().__init__(model_name, provider=provider)
        self.cfg = cfg
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


def _trim_history(messages: list[Any]) -> list[Any]:
    """Build a safe message history for the commit-phase run.

    - Drop the trailing user/retry prompt (the commit prompt replaces it).
    - Drop a trailing model response with unpaired tool calls (would 400).
    A trailing tool-return request is kept: it is a valid open state.
    """
    msgs = list(messages)
    if msgs and isinstance(msgs[-1], ModelRequest):
        has_tool_return = any(isinstance(p, ToolReturnPart) for p in msgs[-1].parts)
        if not has_tool_return:
            msgs.pop()
    while msgs and isinstance(msgs[-1], ModelResponse):
        if any(isinstance(p, ToolCallPart) for p in msgs[-1].parts):
            msgs.pop()
            continue
        break
    return msgs


def _is_budget_error(exc: BaseException) -> bool:
    """True when the main run should hand off to the commit phase.

    Budget/limit breaches and persistent model errors (the server may recover
    inside the commit window; the deliverable may already be partially usable).
    """
    e: BaseException | None = exc
    seen: set[int] = set()
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, (BudgetExceeded, UsageLimitExceeded, ModelAPIError)):
            return True
        if "BudgetExceeded" in type(e).__name__ or "soft time limit" in str(e):
            return True
        e = e.__cause__ or e.__context__
    return False


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

async def _run_bash(command: str, workdir: Path, timeout: float) -> str:
    _log_event("tool_call", tool="bash", command=command, cwd=str(workdir))
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError):
        timed_out = True
        proc.kill()
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except Exception:
            stdout, stderr = b"", b""
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    if timed_out:
        header = (
            f"$ {command}\n[cwd] {workdir}\n"
            f"[exit_code] 124 (KILLED after {timeout:.0f}s timeout - command was too "
            f"slow or hung)\n"
        )
    else:
        header = f"$ {command}\n[cwd] {workdir}\n[exit_code] {proc.returncode}\n"
    result = _truncate(
        header + f"[stdout]\n{out or '<empty>'}\n[stderr]\n{err or '<empty>'}",
        16000,
    )
    _log_event(
        "tool_result",
        tool="bash",
        exit_code="timeout" if timed_out else proc.returncode,
        stdout=out or "<empty>",
        stderr=err or "<empty>",
    )
    return result


async def _read_file(path: str, workdir: Path, max_chars: int) -> str:
    _log_event("tool_call", tool="read_file", path=path)
    file_path = _resolve_path(path, workdir)
    if not file_path.exists():
        result = f"File not found: {file_path}"
        _log_event("tool_result", tool="read_file", result=result)
        return result
    if not file_path.is_file():
        result = f"Not a file: {file_path}"
        _log_event("tool_result", tool="read_file", result=result)
        return result
    result = _truncate(
        await asyncio.to_thread(file_path.read_text, encoding="utf-8"), max_chars
    )
    _log_event("tool_result", tool="read_file", path=path, result=result)
    return result


async def _write_file(path: str, content: str, workdir: Path) -> str:
    _log_event("tool_call", tool="write_file", path=path, content=content)
    file_path = _resolve_path(path, workdir)
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(file_path.write_text, content, encoding="utf-8")
    except Exception as e:
        result = f"Failed to write {file_path}: {e}"
        _log_event("tool_result", tool="write_file", result=result)
        return result
    result = f"Wrote exactly {len(content)} chars to {file_path}"
    _log_event("tool_result", tool="write_file", path=str(file_path), result=result)
    return result


async def _append_file(path: str, content: str, workdir: Path) -> str:
    _log_event("tool_call", tool="append_file", path=path, content=content)
    file_path = _resolve_path(path, workdir)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(_append_text, file_path, content)
    result = f"Appended {len(content)} chars to {file_path}"
    _log_event("tool_result", tool="append_file", result=result)
    return result


def _append_text(file_path: Path, content: str) -> None:
    with file_path.open("a", encoding="utf-8") as f:
        f.write(content)


async def _apply_diff(path: str, diff_content: str, workdir: Path) -> str:
    _log_event("tool_call", tool="apply_diff", path=path, diff=diff_content)
    file_path = _resolve_path(path, workdir)
    if not file_path.exists():
        result = f"File not found: {file_path}"
        _log_event("tool_result", tool="apply_diff", result=result)
        return result
    if not file_path.is_file():
        result = f"Not a file: {file_path}"
        _log_event("tool_result", tool="apply_diff", result=result)
        return result
    _log_event("tool_call", tool="patch", path=str(file_path))
    proc = await asyncio.create_subprocess_exec(
        "patch",
        "-N",
        "-r",
        "-",
        str(file_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(diff_content.encode())
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    output = (
        f"[exit_code] {proc.returncode}\n"
        f"[stdout]\n{out or '<empty>'}\n"
        f"[stderr]\n{err or '<empty>'}"
    )
    if proc.returncode != 0:
        result = f"Failed to apply diff to {file_path}.\n{output}"
    else:
        result = f"Applied diff to {file_path}.\n{output}"
    _log_event("tool_result", tool="apply_diff", exit_code=proc.returncode, result=result)
    return result


def get_pydantic_agent(
    model: TrackedModel, cfg: Config, instrument: bool = False
) -> Agent[LocalAgentDeps, str]:
    agent = Agent(
        model,
        deps_type=LocalAgentDeps,
        system_prompt=SYSTEM_PROMPT,
    )
    if instrument:
        agent.instrument = True

    @agent.tool
    async def bash(ctx: RunContext[LocalAgentDeps], command: str) -> str:
        """Run a shell command in the working directory. Killed after 120 seconds.
        Use absolute paths; combine steps with && where sensible."""
        return await _run_bash(command, ctx.deps.workdir, ctx.deps.bash_timeout)

    @agent.tool
    async def read_file(ctx: RunContext[LocalAgentDeps], path: str) -> str:
        """Read a text file (truncated to a limit). For long files use bash: head/tail/sed -n."""
        return await _read_file(path, ctx.deps.workdir, ctx.deps.max_tool_output)

    @agent.tool
    async def write_file(ctx: RunContext[LocalAgentDeps], path: str, content: str) -> str:
        """Write EXACT content to a file (creates parent dirs, overwrites).
        No trailing newline is added. Use this for final deliverables."""
        return await _write_file(path, content, ctx.deps.workdir)

    @agent.tool
    async def append_file(ctx: RunContext[LocalAgentDeps], path: str, content: str) -> str:
        """Append text to a file (no newline added)."""
        return await _append_file(path, content, ctx.deps.workdir)

    @agent.tool
    async def apply_diff(
        ctx: RunContext[LocalAgentDeps], path: str, diff_content: str
    ) -> str:
        """Apply a unified diff (patch -N) to an existing file."""
        return await _apply_diff(path, diff_content, ctx.deps.workdir)

    return agent


# ---------------------------------------------------------------------------
# Run: main phase + commit phase
# ---------------------------------------------------------------------------

async def _run_main(
    agent: Agent[LocalAgentDeps, str],
    model: TrackedModel,
    cfg: Config,
    prompt: str,
    deps: LocalAgentDeps,
) -> tuple[str, str]:
    """Returns (status, output); status in {'done', 'budget', 'error'}."""
    output = ""
    try:
        async with agent.run_stream_events(
            prompt,
            deps=deps,
            model_settings={"temperature": cfg.temp},
            usage_limits=UsageLimits(
                request_limit=cfg.request_limit,
                total_tokens_limit=cfg.token_budget,
            ),
        ) as events:
            async for event in events:
                out = _log_stream_event(event)
                if out is not None:
                    output = out
        model.log_pending_usage()
        return "done", output
    except Exception as e:
        model.log_pending_usage()
        if _is_budget_error(e):
            _log_event("budget", reason="usage_or_time", detail=str(e)[:200])
            return "budget", output
        _log_event("agent_error", error=f"{type(e).__name__}: {str(e)[:500]}")
        return "error", output


async def _run_commit(
    agent: Agent[LocalAgentDeps, str],
    model: TrackedModel,
    cfg: Config,
    deps: LocalAgentDeps,
    prompt: str,
) -> None:
    remaining = max(0.0, cfg.hard_time - model.elapsed())
    cap = min(cfg.commit_time_cap, remaining)
    if cap < 10:
        _log_event(
            "commit",
            skipped=True,
            reason="not enough time left",
            elapsed_s=round(model.elapsed(), 1),
        )
        return
    history = _trim_history(model.last_messages)
    commit_prompt = COMMIT_PROMPT
    if not history:
        # No conversation to resume: re-state the task so the commit run has context.
        commit_prompt = COMMIT_PROMPT + "\n\nORIGINAL TASK:\n" + prompt
    # The commit phase is allowed to spend the remaining hard-time window.
    model.enable_soft_check = False
    _log_event(
        "commit",
        start=True,
        history_messages=len(history),
        time_cap_s=round(cap, 1),
        elapsed_s=round(model.elapsed(), 1),
    )
    try:
        async with asyncio.timeout(cap):
            async with agent.run_stream_events(
                commit_prompt,
                deps=deps,
                model_settings={
                    "temperature": cfg.temp,
                    "openai_reasoning_effort": cfg.commit_reasoning_effort,
                },
                message_history=history,
                usage_limits=UsageLimits(request_limit=cfg.commit_request_limit),
            ) as events:
                async for event in events:
                    _log_stream_event(event)
        model.log_pending_usage()
        _log_event("commit", done=True, elapsed_s=round(model.elapsed(), 1))
    except (TimeoutError, asyncio.TimeoutError):
        model.log_pending_usage()
        _log_event(
            "commit",
            done=True,
            note="commit time cap reached",
            elapsed_s=round(model.elapsed(), 1),
        )
    except Exception as e:
        model.log_pending_usage()
        _log_event("commit", done=True, error=f"{type(e).__name__}: {str(e)[:300]}")


async def run_prompt(prompt: str, instrument: bool = False) -> str:
    _configure_logging()
    cfg = load_config()
    workdir = _resolve_workdir()
    model = TrackedModel(
        _resolve_model_name(),
        OpenAIProvider(
            base_url=_required_env("OPENAI_BASE_URL"),
            api_key=_required_env("OPENAI_API_KEY"),
        ),
        cfg,
    )
    agent = get_pydantic_agent(model, cfg, instrument=instrument)
    deps = LocalAgentDeps(
        workdir=workdir, bash_timeout=cfg.bash_timeout, max_tool_output=cfg.max_tool_output
    )
    _log_event(
        "agent_start",
        model=_resolve_model_name(),
        base_url=_required_env("OPENAI_BASE_URL"),
        workdir=str(workdir),
        prompt=prompt,
        temp=cfg.temp,
        soft_time=cfg.soft_time,
        hard_time=cfg.hard_time,
        request_limit=cfg.request_limit,
        token_budget=cfg.token_budget,
    )
    status, output = await _run_main(agent, model, cfg, prompt, deps)
    if status == "budget":
        await _run_commit(agent, model, cfg, deps, prompt)
    model.log_pending_usage()
    _log_event(
        "agent_done",
        status=status,
        elapsed_s=round(model.elapsed(), 1),
        output=output,
    )
    return output


def main(instrument: bool = False) -> None:
    parser = argparse.ArgumentParser(description="Run local non-interactive coding agent")
    parser.add_argument("prompt", nargs="+", help="Prompt for the agent")
    args = parser.parse_args()
    prompt = " ".join(args.prompt)
    try:
        output = asyncio.run(run_prompt(prompt, instrument=instrument))
    except Exception as e:
        _log_event("agent_error", error=f"{type(e).__name__}: {str(e)[:500]}")
        print(f"agent failed: {type(e).__name__}: {e}")
        sys.exit(0)
    if output:
        print(output)


if __name__ == "__main__":
    main()
