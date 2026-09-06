"""Dependency-free event aggregation shared by host and generated dev entrypoint."""

import json
import logging


class MetricsCapture(logging.Handler):
    """Aggregate measured events; unknown provider usage remains explicitly unknown."""

    def __init__(self):
        super().__init__()
        self.tokens_in = self.tokens_out = self.cache_read = self.cache_write = 0
        self.tool_calls = 0
        self.status = None
        self.phase_tokens = {}
        self._last = (0, 0, 0)
        self.measurements = {
            "llm_requests": 0,
            "llm_errors": 0,
            "llm_retries": 0,
            "usage_reports": 0,
            "tool_validation_retries": 0,
            "tool_errors": 0,
            "tool_timeouts": 0,
            "tool_completions": 0,
            "phase_executions": 0,
            "phase_retries": 0,
            "budget_events": 0,
        }
        self.configuration = {}

    def emit(self, record):
        try:
            data = json.loads(record.getMessage())
            if not isinstance(data, dict):
                return
            self.consume(data)
        except (TypeError, ValueError, KeyError):
            # A malformed log event must never interrupt agent execution.
            return

    def consume(self, data):
        event = data.get("event")
        counts = {
            "llm_request": "llm_requests",
            "llm_error": "llm_errors",
            "llm_retry": "llm_retries",
            "phase": "phase_executions",
            "phase_retry": "phase_retries",
            "budget": "budget_events",
        }
        if event in counts:
            self.measurements[counts[event]] += 1
        if event == "usage":
            self.measurements["usage_reports"] += 1
            current = tuple(
                int(data.get(k) or 0)
                for k in ("cumulative_input", "cumulative_output", "cumulative_cache_read")
            )
            self.tokens_in, self.tokens_out, self.cache_read = current
            self.cache_write = int(data.get("cumulative_cache_write") or 0)
            phase = data.get("phase")
            if phase:
                bucket = self.phase_tokens.setdefault(phase, {"in": 0, "out": 0, "cache_read": 0})
                for key, value, previous in zip(bucket, current, self._last):
                    bucket[key] += max(0, value - previous)
            self._last = current
            if "reasoning_tokens" in data:
                self.measurements["tokens_reasoning"] = self.measurements.get(
                    "tokens_reasoning", 0
                ) + int(data["reasoning_tokens"])
        elif event == "llm_tool_call":
            self.tool_calls += 1
        elif event == "llm_tool_result" and data.get("validation_retry"):
            self.measurements["tool_validation_retries"] += 1
        elif event == "tool_completed":
            self.measurements["tool_completions"] += 1
            self.measurements["tool_errors"] += int(bool(data.get("failed")))
            key = f"tool_duration_sec.{data['tool']}"
            self.measurements[key] = self.measurements.get(key, 0) + float(data["duration_sec"])
        elif event == "tool_result" and data.get("exit_code") == "timeout":
            self.measurements["tool_timeouts"] += 1
        elif event == "phase_done":
            key = f"phase_duration_sec.{data['id']}"
            self.measurements[key] = self.measurements.get(key, 0) + float(data["duration_s"])
        elif event == "agent_done" and data.get("status"):
            self.status = data["status"]
        elif event == "agent_configuration":
            self.configuration = data.get("configuration", {})

    def snapshot(self):
        return {
            "measurements": dict(self.measurements),
            "configuration": self.configuration,
            # SDK defaults erase the distinction between absent and zero cache usage.
            "usage_status": "partial" if self.measurements["usage_reports"] else "unknown",
            "cache_usage_status": "unknown",
        }
