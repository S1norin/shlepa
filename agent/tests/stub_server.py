"""Shared stub OpenAI-compatible server for agent tests.

Implements POST /v1/chat/completions with both streaming (SSE) and
non-streaming responses, returning a fixed final answer.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FINAL_ANSWER = "Created hello.txt with the exact content hello"

# Captured request state (filled by the stub handler).
stub_state: dict = {}


class StubHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible /v1/chat/completions stub."""

    def log_message(self, *args):  # silence request logging
        pass

    def do_POST(self):  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        stub_state["last_path"] = self.path
        stub_state["last_body"] = body
        base = {
            "id": "chatcmpl-stub",
            "created": 1700000000,
            "model": "stub-model",
        }
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if not body.get("stream"):
            payload = {
                **base,
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": FINAL_ANSWER},
                        "finish_reason": "stop",
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
            },
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
