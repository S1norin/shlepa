"""Baseline agent, vendored from the Universal Agent Competition public repo
(SecureIntelligent/UniversalAgenticCompetitionPublic, agent/local_agent.py).

Kept as close to upstream as possible; adapt with care. See agent/agent.py for
the Harbor wrapper (byte-identical to upstream).
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any
from pathlib import Path

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import FunctionToolCallEvent, FunctionToolResultEvent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.run import AgentRunResultEvent
from pydantic_ai.usage import UsageLimits

MAX_TOOL_OUTPUT_CHARS = 16000
MAX_LOG_VALUE_CHARS = 16000
REQUEST_LIMIT = 1000
LOGGER = logging.getLogger("shlepa-agent")
SECRET_FIELD_MARKERS = ("api_key", "apikey", "token", "secret", "password")


@dataclass(frozen=True)
class LocalAgentDeps:
    workdir: Path


def _truncate(text: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
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
        _log_event("agent_done", output=output)
        return output

    return None


def _resolve_workdir() -> Path:
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


async def _apply_unified_diff(file_path: Path, diff_content: str) -> str:
    _log_event("tool_call", tool="patch", path=str(file_path), diff=diff_content)
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
        _log_event(
            "tool_result", tool="patch", exit_code=proc.returncode, result=result
        )
        return result
    result = f"Applied diff to {file_path}.\n{output}"
    _log_event("tool_result", tool="patch", exit_code=proc.returncode, result=result)
    return result


async def _run_bash(command: str, workdir: Path) -> str:
    _log_event("tool_call", tool="bash", command=command, cwd=str(workdir))
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    result = _truncate(
        f"$ {command}\n"
        f"[cwd] {workdir}\n"
        f"[exit_code] {proc.returncode}\n"
        f"[stdout]\n{out or '<empty>'}\n"
        f"[stderr]\n{err or '<empty>'}"
    )
    _log_event(
        "tool_result",
        tool="bash",
        exit_code=proc.returncode,
        stdout=out or "<empty>",
        stderr=err or "<empty>",
    )
    return result


async def _read_file(path: str, workdir: Path) -> str:
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
    result = _truncate(await asyncio.to_thread(file_path.read_text, encoding="utf-8"))
    _log_event("tool_result", tool="read_file", path=path, result=result)
    return result


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
    result = _truncate(await _apply_unified_diff(file_path, diff_content))
    _log_event("tool_result", tool="apply_diff", path=path, result=result)
    return result


async def _append_file(path: str, content: str, workdir: Path) -> str:
    _log_event("tool_call", tool="append_file", path=path, content=content)
    file_path = _resolve_path(path, workdir)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(_append_text, file_path, content)
    result = f"Appended {len(content)} chars to {file_path}"
    _log_event("tool_result", tool="append_file", path=path, result=result)
    return result


def _append_text(file_path: Path, content: str) -> None:
    with file_path.open("a", encoding="utf-8") as f:
        f.write(content)


def get_pydantic_agent(instrument: bool = False) -> Agent[LocalAgentDeps, str]:
    model_name = _resolve_model_name()
    base_url = _required_env("OPENAI_BASE_URL")
    api_key = _required_env("OPENAI_API_KEY")
    agent = Agent(
        OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(
                base_url=base_url,
                api_key=api_key,
            ),
        ),
        deps_type=LocalAgentDeps,
        system_prompt=(
            "You are a non-interactive coding agent. "
            "Complete the user's request autonomously. "
            "Use tools to inspect files, run commands, and apply focused diffs. "
            "Work in concise steps and explain what you changed in the final response."
        ),
    )
    if instrument:
        agent.instrument = True

    @agent.tool
    async def bash(ctx: RunContext[LocalAgentDeps], command: str) -> str:
        return await _run_bash(command, ctx.deps.workdir)

    @agent.tool
    async def read_file(ctx: RunContext[LocalAgentDeps], path: str) -> str:
        return await _read_file(path, ctx.deps.workdir)

    @agent.tool
    async def apply_diff(
        ctx: RunContext[LocalAgentDeps], path: str, diff_content: str
    ) -> str:
        return await _apply_diff(path, diff_content, ctx.deps.workdir)

    @agent.tool
    async def append_file(
        ctx: RunContext[LocalAgentDeps], path: str, content: str
    ) -> str:
        return await _append_file(path, content, ctx.deps.workdir)

    return agent


async def _consume_stream_events(stream: Any) -> str:
    final_output = ""

    async def consume(events: Any) -> None:
        nonlocal final_output
        async for event in events:
            output = _log_stream_event(event)
            if output is not None:
                final_output = output

    if hasattr(stream, "__aenter__"):
        async with stream as events:
            await consume(events)
    else:
        await consume(stream)

    return final_output


async def run_prompt(prompt: str, instrument: bool = False) -> str:
    _configure_logging()
    workdir = _resolve_workdir()
    _log_event(
        "agent_start",
        model=_resolve_model_name(),
        base_url=_required_env("OPENAI_BASE_URL"),
        workdir=str(workdir),
        prompt=prompt,
    )
    agent = get_pydantic_agent(instrument=instrument)
    return await _consume_stream_events(
        agent.run_stream_events(
            prompt,
            deps=LocalAgentDeps(workdir=workdir),
            usage_limits=UsageLimits(request_limit=REQUEST_LIMIT),
        )
    )


def main(instrument: bool = False) -> None:
    parser = argparse.ArgumentParser(
        description="Run local non-interactive coding agent"
    )
    parser.add_argument("prompt", nargs="+", help="Prompt for the agent")
    args = parser.parse_args()
    prompt = " ".join(args.prompt)
    print(asyncio.run(run_prompt(prompt, instrument=instrument)))


if __name__ == "__main__":
    main()
