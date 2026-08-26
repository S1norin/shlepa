"""Validate that every shlepa command cited in docs/runbook.md exists.

The runbook is the day-to-day manual for humans and dev agents alike, so
any cited subcommand must be a real one. Commands are extracted from code
spans (fenced blocks and inline backticks) only, so prose mentions of the
word "shlepa" are not treated as commands.
"""

from __future__ import annotations

import re
from pathlib import Path

from typer.main import get_command

from shlepa_cli.main import app

RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "runbook.md"

KNOWN_COMMANDS = {
    "run",
    "smoke",
    "doctor",
    "zip",
    "submit-test",
    "clean",
    "help",
    "task",
}


def _code_spans(text: str):
    """Yield fenced code blocks and inline code spans from markdown."""
    for m in re.finditer(r"```[^\n]*\n(.*?)```", text, flags=re.DOTALL):
        yield m.group(1)
    for m in re.finditer(r"`([^`\n]+)`", text):
        yield m.group(1)


def _cited_commands() -> list[str]:
    cited: list[str] = []
    for span in _code_spans(RUNBOOK.read_text()):
        for line in span.splitlines():
            for m in re.finditer(r"\bshlepa\s+([A-Za-z][\w-]*)", line):
                cited.append(m.group(1))
    return cited


def test_runbook_exists() -> None:
    assert RUNBOOK.is_file()


def test_known_commands_match_the_cli() -> None:
    names = set(get_command(app).commands)
    assert KNOWN_COMMANDS == names


def test_runbook_cites_only_existing_commands() -> None:
    cited = _cited_commands()
    assert cited, "the runbook cites no shlepa commands at all"
    unknown = sorted(set(cited) - KNOWN_COMMANDS)
    assert not unknown, f"unknown shlepa subcommands cited: {unknown}"
