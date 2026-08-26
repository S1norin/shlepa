"""shlepa run --dry-run: prints resolved tasks + model without executing."""

from typer.testing import CliRunner

from shlepa_cli.main import app

runner = CliRunner()


def _make_repo(base):
    (base / ".git").mkdir()
    (base / "agent").mkdir()
    exp = base / "experiments"
    exp.mkdir()
    (exp / "all.yaml").write_text("name: all\ntasks: all\n")
    task = base / "tasks" / "contest-hello-file"
    task.mkdir(parents=True)
    (task / "task.toml").write_text('schema_version = "1.2"\nname = "Hello File"\n')
    task2 = base / "tasks" / "contest-bye-file"
    task2.mkdir(parents=True)
    (task2 / "task.toml").write_text('schema_version = "1.2"\nname = "Bye File"\n')


def test_run_dry_run_lists_tasks_and_model(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LOCAL_AGENT_MODEL", raising=False)

    result = runner.invoke(app, ["run", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "preset: all" in result.output
    assert "model: (from env)" in result.output
    assert "contest-bye-file" in result.output
    assert "contest-hello-file" in result.output
    # It must not try to execute the (unimplemented) engine.
    assert "not implemented" not in result.output


def test_run_dry_run_preset_model_override(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    (tmp_path / "experiments" / "quick.yaml").write_text(
        "name: quick\ntasks: [contest-hello-file]\nmodel: gpt-4o-mini\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "env-model")

    result = runner.invoke(app, ["run", "quick", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "model: gpt-4o-mini" in result.output
    assert "contest-hello-file" in result.output
    assert "contest-bye-file" not in result.output


def test_run_dry_run_unknown_preset_errors(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["run", "does-not-exist", "--dry-run"])
    assert result.exit_code != 0
    assert "does-not-exist" in result.output
