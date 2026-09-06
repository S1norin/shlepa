"""Streaming OpenAI stub for run-engine tests (SSE chat completions)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FINAL_ANSWER = "Done: the file was created."

# The v6 hard-cycle pipeline: plan -> work -> review (relay) -> plan -> work
# (exactly max_cycles plan/work cycles; the relay runs between cycles only).
# The stub is pipeline-aware on the user-message phase headers: the plan
# request ("PLAN PHASE") gets a typed final_result(PlanResult), the work
# request ("WORK PHASE") a typed final_result(WorkResult) with
# summary=FINAL_ANSWER, and the review relay request ("REVIEW PHASE") a typed
# final_result(ReviewResult) in the v6 relay shape. Matching order matters:
# review is checked BEFORE work because the relay request resumes the work
# transcript and carries its "WORK PHASE" user message in the history.
# Everything else (emergency) gets the plain FINAL_ANSWER text.
PLAN_RESULT_ARGS = {
    "goal": "write the requested file",
    "findings": "",
    "steps": ["write the file"],
}

WORK_RESULT_ARGS = {
    "summary": FINAL_ANSWER,
    "findings": "",
    "deliverable": "hello.txt",
    "confidence": 0.9,
}

REVIEW_RESULT_ARGS = {
    "summary": "Wrote hello.txt with the requested content.",
    "done": True,
    "problems": [],
    "hints_next": [],
}


def _has_phase_header(body: dict, header: str) -> bool:
    for m in body.get("messages", []):
        if m.get("role") == "user" and header in (m.get("content") or ""):
            return True
    return False


def _result_args(body: dict) -> dict | None:
    """Typed final_result args for the request's phase, or None for a plain
    text answer."""
    if _has_phase_header(body, "PLAN PHASE"):
        return PLAN_RESULT_ARGS
    if _has_phase_header(body, "REVIEW PHASE"):
        return REVIEW_RESULT_ARGS
    if _has_phase_header(body, "WORK PHASE"):
        return WORK_RESULT_ARGS
    return None


def _is_work_request(body: dict) -> bool:
    for m in body.get("messages", []):
        if m.get("role") == "user" and "WORK PHASE" in (m.get("content") or ""):
            return True
    return False


class StreamStubHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        base = {
            "id": "chatcmpl-stub",
            "created": 1700000000,
            "model": "stub-model",
        }
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        args = _result_args(body)
        if not body.get("stream"):
            if args is not None:
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_stub",
                            "type": "function",
                            "function": {
                                "name": "final_result",
                                "arguments": json.dumps(args),
                            },
                        }
                    ],
                }
                finish = "tool_calls"
            else:
                message = {"role": "assistant", "content": FINAL_ANSWER}
                finish = "stop"
            payload = {
                **base,
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": finish,
                    }
                ],
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
        if args is not None:
            chunks.append(
                {
                    **base,
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_stub",
                                        "type": "function",
                                        "function": {
                                            "name": "final_result",
                                            "arguments": json.dumps(args),
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )
            finish = "tool_calls"
        else:
            chunks.append(
                {
                    **base,
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": FINAL_ANSWER},
                            "finish_reason": None,
                        }
                    ],
                }
            )
            finish = "stop"
        chunks.append(
            {
                **base,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                "usage": usage,
            }
        )
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def start_stream_stub() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), StreamStubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"
