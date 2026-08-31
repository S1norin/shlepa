"""Shared stub OpenAI-compatible server for agent tests.

Implements POST /v1/chat/completions with both streaming (SSE) and
non-streaming responses, returning a fixed final answer.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FINAL_ANSWER = "Created hello.txt with the exact content hello"

# A full plan -> work -> commit script for end-to-end tests of the typed
# pipeline (the default single free-text final cannot complete plan/work).
PIPELINE_SCRIPT = [
    {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "goal": "write hello.txt with the exact content hello",
                "findings": "",
                "steps": ["write the file", "verify it"],
                "decision": "work",
            },
        }
    },
    {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "summary": "wrote hello.txt and verified it",
                "findings": "",
                "deliverable": "hello.txt",
                "confidence": 1.0,
            },
        }
    },
    {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "status": "ok",
                "verdict": "done",
                "artifact": "hello.txt",
                "checks": ["re-read the file -> content matches"],
                "notes": FINAL_ANSWER,
            },
        }
    },
]

# Captured request state (filled by the stub handler).
#   last_path / last_body: the most recent request
#   bodies: every request body, in order
#   script: optional list of response steps; step i answers request i+1.
#     step {"final": "text"}  -> plain final answer (default FINAL_ANSWER)
#     step {"tool_call": {"name": "bash", "arguments": {...}}} -> assistant tool call
#     step {"error": 500}     -> HTTP error response (OpenAI-style error body)
#     optional per step: "reasoning": model thinking text, returned as
#     optional per step: "delay": seconds to sleep before responding
#     (used to force phase time-caps in tests).
stub_state: dict = {"last_path": None, "last_body": None, "bodies": [], "script": None}


def reset_stub_state() -> None:
    stub_state.clear()
    stub_state.update({"last_path": None, "last_body": None, "bodies": [], "script": None})


class StubHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible /v1/chat/completions stub."""

    def log_message(self, *args):  # silence request logging
        pass

    def _step(self) -> dict:
        script = stub_state.get("script") or [{"final": FINAL_ANSWER}]
        index = min(len(stub_state["bodies"]) - 1, len(script) - 1)
        return script[index]

    def _reasoning(self, step: dict) -> str | None:
        return step.get("reasoning")

    def do_POST(self):  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        stub_state["bodies"].append(body)
        stub_state["last_path"] = self.path
        stub_state["last_body"] = body
        step = self._step()
        if step.get("error") is not None:
            status = int(step["error"])
            payload = {
                "error": {
                    "message": step.get("error_message", f"stub error {status}"),
                    "type": "stub_error",
                }
            }
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if step.get("delay"):
            time.sleep(float(step["delay"]))
        tool_call = step.get("tool_call")
        base = {
            "id": "chatcmpl-stub",
            "created": 1700000000,
            "model": "stub-model",
        }
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if not body.get("stream"):
            if tool_call:
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_stub",
                            "type": "function",
                            "function": {
                                "name": tool_call["name"],
                                "arguments": json.dumps(tool_call.get("arguments", {})),
                            },
                        }
                    ],
                }
                finish = "tool_calls"
            else:
                message = {"role": "assistant", "content": step.get("final", FINAL_ANSWER)}
                if self._reasoning(step) is not None:
                    message["reasoning_content"] = self._reasoning(step)
                finish = "stop"
            payload = {
                **base,
                "object": "chat.completion",
                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                "usage": usage,
            }
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if tool_call:
            tool_delta = {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_stub",
                        "type": "function",
                        "function": {
                            "name": tool_call["name"],
                            "arguments": json.dumps(tool_call.get("arguments", {})),
                        },
                    }
                ]
            }
            reasoning = self._reasoning(step)
            chunks = [
                {
                    **base,
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": None},
                            "finish_reason": None,
                        }
                    ],
                }
            ]
            if reasoning is not None:
                chunks.append(
                    {
                        **base,
                        "object": "chat.completion.chunk",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"reasoning_content": reasoning},
                                "finish_reason": None,
                            }
                        ],
                    }
                )
            chunks += [
                {
                    **base,
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": tool_delta, "finish_reason": None}],
                },
                {
                    **base,
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                },
            ]
        else:
            final = step.get("final", FINAL_ANSWER)
            chunks = [
                {
                    **base,
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": ""},
                            "finish_reason": None,
                        }
                    ],
                }
            ]
            if self._reasoning(step) is not None:
                chunks.append(
                    {
                        **base,
                        "object": "chat.completion.chunk",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"reasoning_content": self._reasoning(step)},
                                "finish_reason": None,
                            }
                        ],
                    }
                )
            chunks += [
                {
                    **base,
                    "object": "chat.completion.chunk",
                    "choices": [
                        {"index": 0, "delta": {"content": final}, "finish_reason": None}
                    ],
                },
                {
                    **base,
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": usage,
                },
            ]
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def start_stub_server() -> tuple[ThreadingHTTPServer, str]:
    """Start the stub on a random localhost port; return (server, base_url)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"
