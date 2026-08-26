"""Command-line entry point: python -m shlepa_agent "instruction"."""

import os


def main() -> None:
    from shlepa_agent import core

    provider = None
    if os.environ.get("SLEPA_OTEL_ENABLED") == "1":
        # Imported only when tracing is requested, so the baseline
        # never touches the otel SDK stack.
        from shlepa_agent.telemetry import configure

        provider = configure()

    try:
        core.main(instrument=True if provider is not None else False)
    finally:
        if provider is not None:
            provider.shutdown()  # flushes pending spans


if __name__ == "__main__":
    main()
