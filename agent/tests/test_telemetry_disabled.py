"""Telemetry-off test: baseline must not import the otel SDK stack."""

import asyncio
import sys

BLOCKED_PREFIXES = (
    "opentelemetry.sdk",
    "opentelemetry.exporter",
    "openinference",
)


def _blocked(name: str) -> bool:
    return any(name == p or name.startswith(p + ".") for p in BLOCKED_PREFIXES)


class _OtelBlocker:
    """Meta-path hook that fails any import of the otel SDK stack."""

    def find_spec(self, name, path=None, target=None):
        if _blocked(name):
            raise ImportError(f"blocked otel import in baseline: {name}")
        return None


def test_baseline_runs_without_otel_sdk(monkeypatch, stub_openai, tmp_path):
    before = {m for m in sys.modules if _blocked(m)}
    blocker = _OtelBlocker()
    sys.meta_path.insert(0, blocker)
    monkeypatch.delenv("SLEPA_OTEL_ENABLED", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))
    try:
        from shlepa_agent.core import run_prompt

        output = asyncio.run(
            run_prompt("Create hello.txt with the exact content hello")
        )
    finally:
        sys.meta_path.remove(blocker)

    assert output
    leaked = {m for m in sys.modules if _blocked(m)} - before
    assert not leaked, f"otel SDK modules imported by baseline: {leaked}"
