"""Integration test: baseline agent loop against a stub OpenAI-compatible server."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FINAL_ANSWER = "Created hello.txt with the exact content hello"

# Captured request state (filled by the stub handler).
stub_state: dict = {}


class _StubHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible /v1/chat/completions stub (stream + non-stream)."""

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
            {**base, "object": "chat.completion.chunk",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""},
                          "finish_reason": None}]},
            {**base, "object": "chat.completion.chunk",
             "choices": [{"index": 0, "delta": {"content": FINAL_ANSWER},
                          "finish_reason": None}]},
            {**base, "object": "chat.completion.chunk",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": usage},
        ]
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


import pytest  # noqa: E402


@pytest.fixture
def stub_openai():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()


def test_baseline_completes_against_stub(monkeypatch, stub_openai, tmp_path):
    from shlepa_agent.core import run_prompt

    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))

    output = asyncio.run(run_prompt("Create hello.txt with the exact content hello"))

    assert output == FINAL_ANSWER
    body = stub_state["last_body"]
    assert body["model"] == "stub-model"
    system_prompt = body["messages"][0]["content"]
    assert "non-interactive coding agent" in system_prompt
