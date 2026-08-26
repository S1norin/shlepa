"""Shared pytest fixtures for the agent test suite."""

import pytest

from stub_server import start_stub_server


@pytest.fixture
def stub_openai():
    """OpenAI-compatible stub server; yields its base URL (http://host:port/v1)."""
    server, base_url = start_stub_server()
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
