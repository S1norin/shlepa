"""shlepa command-line interface (entry point)."""

import typer

from shlepa_cli import __version__

app = typer.Typer(
    name="shlepa",
    help="Shlepa development CLI.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"shlepa {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print the CLI version and exit.",
    ),
) -> None:
    """Shlepa development CLI."""


def _not_implemented(command: str) -> None:
    typer.echo(f"shlepa {command}: not implemented yet")
    raise typer.Exit(code=1)


@app.command()
def run(preset: str = typer.Option("all", help="Experiment preset name")) -> None:
    """Run the dev experiment loop for a preset."""
    _not_implemented(f"run {preset}")


@app.command()
def smoke() -> None:
    """Fast end-to-end check (doctor + one trivial task + MLflow run)."""
    _not_implemented("smoke")


@app.command()
def doctor(
    probe: bool = typer.Option(
        False,
        "--probe",
        help="Additionally run one chat completion (best effort).",
    ),
) -> None:
    """Check LLM endpoint, MLflow, and docker availability."""
    from shlepa_cli.config import get_settings
    from shlepa_cli.doctor import run_doctor

    settings = get_settings()
    results, probe_info = run_doctor(settings, probe=probe)
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        typer.echo(f"{status}  {result.name}: {result.detail}")
    if probe_info is not None:
        typer.echo(f"probe  chat completion: {probe_info}")
    passed = sum(1 for r in results if r.ok)
    typer.echo(f"doctor: {passed}/{len(results)} checks passed")
    model_mismatch = any(
        r.name == "llm_model" and not r.ok and r.model_actual is not None
        for r in results
    )
    if model_mismatch:
        raise typer.Exit(code=2)
    if passed != len(results):
        raise typer.Exit(code=1)


@app.command()
def submit_test(ci: bool = typer.Option(False, help="CI mode (endpoint_class=ci)")) -> None:
    """Strict contest-faithful test via Harbor inside the acp container."""
    _not_implemented(f"submit-test--ci={ci}" if ci else "submit-test")


@app.command()
def zip(register: bool = typer.Option(False, help="Register in the MLflow model registry")) -> None:
    """Build the submission zip (telemetry stripped)."""
    _not_implemented(f"zip--register={register}" if register else "zip")


@app.command()
def clean() -> None:
    """Remove tmp/ files older than 7 days."""
    _not_implemented("clean")


@app.command("help")
def help_command(
    topic: str | None = typer.Argument(None, help="Command to show help for."),
) -> None:
    """CLI usage reference (optionally for a single command)."""
    import click

    from typer.main import get_command

    click_command = get_command(app)
    ctx = click.Context(click_command)
    if topic:
        sub = click_command.get_command(ctx, topic)
        if sub is None:
            typer.echo(f"Unknown command: {topic}", err=True)
            raise typer.Exit(code=1)
        typer.echo(sub.get_help(click.Context(sub)))
    else:
        typer.echo(click_command.get_help(ctx))


task_app = typer.Typer(help="Task management commands.")


@task_app.command()
def new(name: str) -> None:
    """Scaffold a new task from the template."""
    _not_implemented(f"task new {name}")


app.add_typer(task_app, name="task")


if __name__ == "__main__":
    app()
