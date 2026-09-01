"""Streaming OpenAI stub for run-engine tests (SSE chat completions)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FINAL_ANSWER = "Done: the file was created."

# The 4-phase pipeline: plan -> work -> commit (the review phase). The stub
# is pipeline-aware: the plan request (user message with "PLAN PHASE") gets a
# final_result tool call with decision="commit" (trivial task shortcut), the
# commit/review request ("REVIEW PHASE", the phase prompt's current header)
# gets a typed final_result(ReviewResult) with notes=FINAL_ANSWER,
# everything else (emergency) gets the plain FINAL_ANSWER text.
PLAN_RESULT_ARGS = {
    "goal": "write the requested file",
    "findings": "",
    "steps": ["write the file"],
    "decision": "commit",
}

COMMIT_RESULT_ARGS = {
    "status": "ok",
    "verdict": "done",
    "artifact": "hello.txt",
    "checks": ["re-read the file -> content matches"],
    "notes": FINAL_ANSWER,
}


def _is_plan_request(body: dict) -> bool:
    for m in body.get("messages", []):
        if m.get("role") == "user" and "PLAN PHASE" in (m.get("content") or ""):
            return True
    return False


def _is_commit_request(body: dict) -> bool:
    for m in body.get("messages", []):
        if m.get("role") == "user" and "REVIEW PHASE" in (m.get("content") or ""):
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
        if not body.get("stream"):
            if _is_plan_request(body):
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_stub",
                            "type": "function",
                            "function": {
                                "name": "final_result",
                                "arguments": json.dumps(PLAN_RESULT_ARGS),
                            },
                        }
                    ],
                }
                finish = "tool_calls"
            elif _is_commit_request(body):
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_stub",
                            "type": "function",
                            "function": {
                                "name": "final_result",
                                "arguments": json.dumps(COMMIT_RESULT_ARGS),
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
        if _is_plan_request(body):
            args = PLAN_RESULT_ARGS
        elif _is_commit_request(body):
            args = COMMIT_RESULT_ARGS
        if _is_plan_request(body) or _is_commit_request(body):
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
