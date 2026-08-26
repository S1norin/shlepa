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
def doctor() -> None:
    """Check LLM endpoint, MLflow, and docker availability."""
    _not_implemented("doctor")


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
