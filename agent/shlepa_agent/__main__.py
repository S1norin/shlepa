"""Command-line entry point: python -m shlepa_agent "instruction"."""

import os


def main() -> None:
    from shlepa_agent import core

    if os.environ.get("SLEPA_OTEL_ENABLED") != "1":
        core.main(instrument=False)
        return

    # Imported only when tracing is requested, so the baseline
    # never touches the otel SDK stack.
    from shlepa_agent.telemetry import configure

    provider = configure()
    tracer = provider.get_tracer("shlepa-agent")
    try:
        # Root span for the whole run; carries the task slug so traces
        # can be grouped per task in Jaeger.
        with tracer.start_as_current_span("agent.run") as span:
            span.set_attribute("task", os.environ.get("SLEPA_TASK_SLUG", "dev-run"))
            core.main(instrument=True)
    finally:
        provider.shutdown()  # flushes pending spans


if __name__ == "__main__":
    main()
