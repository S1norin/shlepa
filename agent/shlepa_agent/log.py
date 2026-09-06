"""Structured JSON logging for the agent.

Every event is one JSON object on stdout: ``{"event": ..., ...fields}``.
Values are truncated (``MAX_LOG_VALUE_CHARS``) and secret-looking fields are
redacted. The CLI dev engine parses a subset of these events from the agent
stdout (``usage``, ``agent_start``, ``agent_done``, ``agent_error``,
``commit``) — keep the event names and those fields stable.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from pydantic import BaseModel
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartEndEvent,
    ThinkingPart,
    RetryPromptPart,
)
from pydantic_ai.run import AgentRunResultEvent

MAX_LOG_VALUE_CHARS = 16000
LOGGER = logging.getLogger("shlepa-agent")
# NOTE: "token" on its own is too broad (would redact usage fields like input_tokens).
SECRET_FIELD_MARKERS = ("api_key", "apikey", "secret", "password", "auth_token", "access_token")


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


def _log_event_raw(event: str, **fields: Any) -> None:
    """Emit an event with raw, untruncated values (llm_thinking must be complete)."""
    _configure_logging()
    payload = {"event": event}
    payload.update(fields)
    LOGGER.info(json.dumps(payload, ensure_ascii=False, default=str))


def _log_stream_event(event: Any) -> Any:
    """Log one stream event; returns the run output on the result event."""
    if isinstance(event, PartEndEvent) and isinstance(event.part, ThinkingPart):
        _log_event_raw("llm_thinking", index=event.index, content=event.part.content)
        return None

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
            validation_retry=isinstance(result, RetryPromptPart),
            result=getattr(result, "content", getattr(event, "content", None)),
        )
        return None

    if isinstance(event, AgentRunResultEvent):
        raw = event.result.output
        usage = getattr(event.result, "usage", None)
        if usage is not None:
            _log_event(
                "run_usage",
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                requests=getattr(usage, "requests", None),
                tool_calls=getattr(usage, "tool_calls", None),
            )
        if isinstance(raw, BaseModel):
            _log_event("agent_done", output=raw.model_dump_json())
        else:
            _log_event("agent_done", output=str(raw))
        return raw

    return None
