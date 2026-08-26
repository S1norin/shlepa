"""Validate the embedded task.toml example in docs/tasks.md.

The docs example must stay a *valid* task: parseable TOML, required
sections present, and discoverable by the real task parser.
"""

import re
import tomllib
from pathlib import Path

from shlepa_cli import tasks as tasks_module
from shlepa_cli.task_new import KNOWN_SOURCES

DOCS = Path(__file__).resolve().parents[2] / "docs" / "tasks.md"


def _example_toml() -> str:
    text = DOCS.read_text()
    match = re.search(r"```toml\n(.*?)```", text, re.DOTALL)
    assert match, "docs/tasks.md must contain a ```toml example block"
    return match.group(1)


def test_example_is_parseable_with_required_sections():
    data = tomllib.loads(_example_toml())
    assert data["schema_version"] == "1.2"
    assert data["task"]["name"]
    assert "description" in data["task"]
    assert data["metadata"]["source"] in KNOWN_SOURCES
    assert "timeout_sec" in data["verifier"]
    assert "timeout_sec" in data["agent"]
    for key in (
        "build_timeout_sec",
        "cpus",
        "memory_mb",
        "storage_mb",
        "allow_internet",
    ):
        assert key in data["environment"], key


def test_example_is_discoverable_by_the_real_parser(tmp_path):
    example = _example_toml()
    task_dir = tmp_path / "tasks" / "own-example-task"
    task_dir.mkdir(parents=True)
    (task_dir / "task.toml").write_text(example)

    found = tasks_module.discover_tasks(tmp_path / "tasks")

    assert [t.slug for t in found] == ["own-example-task"]
    assert found[0].name == "own/example-task"
    assert found[0].timeout_sec == 300.0
    assert found[0].verifier_timeout_sec == 120.0
