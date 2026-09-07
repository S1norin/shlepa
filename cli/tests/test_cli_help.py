"""CLI scaffolding tests: --version and help listing."""

from typer.testing import CliRunner

from shlepa_cli.main import app

runner = CliRunner()

EXPECTED_COMMANDS = [
    "clean",
    "compliance",
    "doctor",
    "run",
    "smoke",
    "submit-test",
    "task",
    "zip",
]


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_help_lists_all_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in EXPECTED_COMMANDS:
        assert command in result.output, f"missing command in help: {command}"


def test_help_subcommand_works():
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "run" in result.output
