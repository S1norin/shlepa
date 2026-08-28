"""shlepa command-line interface (entry point)."""

import os
from pathlib import Path

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


def _register_submission(settings, out) -> None:
    """Register the built submission in the MLflow model registry."""
    from shlepa_cli.mlflow_client import get_mlflow_client
    from shlepa_cli.zip_register import register_submission

    try:
        client = get_mlflow_client(settings)
    except ValueError as exc:
        typer.echo(f"zip: MLflow not configured: {exc}", err=True)
        raise typer.Exit(code=1)
    version = register_submission(client, settings, out)
    typer.echo(f"registered: shlepa:{version}")


@app.command()
def run(
    preset: str = typer.Argument("all", help="Experiment preset name"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print resolved tasks and model, do not run."
    ),
) -> None:
    """Run the dev experiment loop for a preset."""
    from shlepa_cli import tasks as tasks_module
    from shlepa_cli.config import get_settings

    settings = get_settings()
    try:
        preset_obj = tasks_module.load_preset_by_name(settings.repo_root, preset)
        all_tasks = tasks_module.discover_tasks(settings.repo_root / "tasks")
        resolved = tasks_module.resolve_tasks(preset_obj, all_tasks)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)
    if dry_run:
        model = preset_obj.model or settings.local_agent_model or "(from env)"
        typer.echo(f"preset: {preset_obj.name}")
        typer.echo(f"model: {model}")
        typer.echo(f"tasks ({len(resolved)}):")
        for task in resolved:
            typer.echo(f"  - {task.slug} ({task.name})")
        return

    from shlepa_cli import run_engine

    model = preset_obj.model or settings.local_agent_model
    no_docker = os.environ.get("SLEPA_NO_DOCKER") == "1"
    batch_id = run_engine.make_batch_id()
    typer.echo(
        f"preset: {preset_obj.name} | model: {model or '(env)'} | "
        f"mode: {'no-docker' if no_docker else 'container'} | "
        f"batch: {batch_id} | tasks: {len(resolved)}"
    )
    mlflow_client = None
    if settings.mlflow_tracking_uri:
        try:
            from shlepa_cli.mlflow_client import get_mlflow_client

            mlflow_client = get_mlflow_client(settings)
        except ValueError as exc:
            typer.echo(f"warning: MLflow not configured: {exc}", err=True)
    results = run_engine.run_preset(
        settings,
        preset_obj,
        resolved,
        model=model,
        no_docker=no_docker,
        mlflow_client=mlflow_client,
        batch_id=batch_id,
    )
    typer.echo("")
    typer.echo(run_engine.format_summary(results))
    if not results:
        raise typer.Exit(code=1)


@app.command("trace-export")
def trace_export(
    batch: str = typer.Option(
        ..., "--batch", help="SLEPA batch id (printed by 'shlepa run')"
    ),
    out: Path = typer.Option(
        None,
        "--out",
        help="Output dir (default tmp/trace-export/<batch>/)",
    ),
    experiment: str = typer.Option(
        None,
        "--experiment",
        help="Trace experiment name/id (default from settings)",
    ),
) -> None:
    """Export the agent traces of one batch as JSON + digests + manifest."""
    from shlepa_cli import trace_export as trace_export_module
    from shlepa_cli.config import get_settings
    from shlepa_cli.mlflow_client import get_mlflow_client

    settings = get_settings()
    try:
        client = get_mlflow_client(settings)
    except ValueError as exc:
        typer.echo(f"trace-export: MLflow not configured: {exc}", err=True)
        raise typer.Exit(code=1)
    out_dir = out or settings.repo_root / "tmp" / "trace-export" / batch
    try:
        summary = trace_export_module.export_batch(
            client, settings, batch, out_dir, experiment
        )
    except trace_export_module.TraceBatchNotFound as exc:
        typer.echo(f"trace-export: {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(
        f"exported {summary['traces']} trace(s) for batch {batch} -> {out_dir}"
    )


@app.command()
def smoke(
    ci: bool = typer.Option(
        False,
        "--ci",
        help=(
            "Use the secondary CI endpoint (CI_* settings, falling back to "
            "the main endpoint) and log to the shlepa-ci experiment."
        ),
    ),
) -> None:
    """End-to-end check: doctor + contest-hello-file task + MLflow run."""
    from shlepa_cli import smoke as smoke_module
    from shlepa_cli.config import get_settings

    settings = get_settings()
    typer.echo("shlepa smoke" + (" --ci" if ci else ""))
    ok = smoke_module.run_smoke(settings, ci=ci, out=typer.echo)
    typer.echo(f"smoke: {'PASS' if ok else 'FAIL'}")
    raise typer.Exit(code=0 if ok else 1)


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


@app.command("submit-test")
def submit_test(
    tasks: list[str] = typer.Argument(
        None, help="Task slugs (default: all discoverable tasks)."
    ),
    ci: bool = typer.Option(
        False, "--ci", help="CI mode (CI endpoint, endpoint_class=ci)."
    ),
) -> None:
    """Strict contest-faithful test via Harbor inside the acp container."""
    from shlepa_cli import submit_test as submit_test_module
    from shlepa_cli.config import get_settings

    settings = get_settings()
    mlflow_client = None
    if settings.mlflow_tracking_uri:
        try:
            from shlepa_cli.mlflow_client import get_mlflow_client

            mlflow_client = get_mlflow_client(settings)
        except ValueError as exc:
            typer.echo(f"warning: MLflow not configured: {exc}", err=True)
    ok = submit_test_module.run_submit_test(
        settings,
        tasks,
        ci=ci,
        out=typer.echo,
        mlflow_client=mlflow_client,
    )
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def zip(register: bool = typer.Option(False, help="Register in the MLflow model registry")) -> None:
    """Build the submission zip (telemetry stripped)."""
    from shlepa_cli.config import get_settings
    from shlepa_cli.zip_build import ZipBuildError, build_submission_zip

    settings = get_settings()
    try:
        out = build_submission_zip(settings.repo_root)
    except ZipBuildError as exc:
        typer.echo(f"zip: {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"zip: {out} ({out.stat().st_size} bytes)")
    if register:
        _register_submission(settings, out)


@app.command()
def clean(
    days: int = typer.Option(
        7, "--days", min=1, help="Max age in days (default 7)."
    ),
) -> None:
    """Remove tmp/ workspaces older than the given number of days."""
    from shlepa_cli import clean as clean_module
    from shlepa_cli.config import get_settings

    settings = get_settings()
    removed = clean_module.clean(
        settings.repo_root / "tmp", max_age_days=days
    )
    if not removed:
        typer.echo("clean: nothing to remove")
        return
    for path in removed:
        typer.echo(f"removed: {path}")


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
    """Scaffold a new task: shlepa task new <source>-<slug>."""
    from shlepa_cli import task_new as task_new_module
    from shlepa_cli.config import get_settings

    settings = get_settings()
    try:
        task_dir = task_new_module.scaffold(settings.repo_root / "tasks", name)
    except (task_new_module.TaskNameError, FileExistsError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)
    typer.echo(f"created: {task_dir}")


app.add_typer(task_app, name="task")


if __name__ == "__main__":
    app()
