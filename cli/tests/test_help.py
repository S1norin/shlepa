"""Tests for 'shlepa help' (usage reference)."""

from typer.testing import CliRunner

from shlepa_cli.main import app


def test_help_root():
    runner = CliRunner()
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "Usage" in result.output
    assert "Commands" in result.output
    for command in ("compliance", "doctor", "run", "smoke", "submit-test", "zip", "clean", "task"):
        assert command in result.output, f"missing {command}"


def test_help_single_command():
    runner = CliRunner()
    result = runner.invoke(app, ["help", "run"])
    assert result.exit_code == 0
    assert "preset" in result.output


def test_help_group_command():
    runner = CliRunner()
    result = runner.invoke(app, ["help", "task"])
    assert result.exit_code == 0
    assert "new" in result.output


def test_help_unknown_command():
    runner = CliRunner()
    result = runner.invoke(app, ["help", "nope-nope"])
    assert result.exit_code == 1
    assert "Unknown command" in result.output
