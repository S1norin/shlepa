"""Scaffolding for new local tasks (``shlepa task new <source>-<slug>``).

Creates tasks/<name>/ with a task.toml following the contest schema
1.2, an instruction template, an acp-based environment Dockerfile, a
pytest verifier skeleton and a solution/ placeholder.
"""

from __future__ import annotations

import re
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)+$")
KNOWN_SOURCES = ("contest", "bench", "own")


class TaskNameError(ValueError):
    """Raised for invalid task names or unknown source prefixes."""


TASK_TOML = """\
schema_version = "1.2"

[task]
name = "{display}"
description = "TODO: one-line task description"
authors = []
keywords = []

[metadata]
difficulty = "easy"
category = "programming"
tags = []
source = "{source}"

[verifier]
timeout_sec = 120.0

[agent]
timeout_sec = 300.0

[environment]
build_timeout_sec = 600.0
cpus = 1
memory_mb = 2048
storage_mb = 10240
gpus = 0
allow_internet = true
mcp_servers = []

[verifier.env]

[environment.env]

[solution.env]
"""

INSTRUCTION_MD = """\
# TODO: write the task instruction

Describe the goal, the materials provided in the environment, and the
exact expected output. Keep it self-contained: the agent sees only this
text (plus what it can discover in its working directory).
"""

DOCKERFILE = """\
FROM secureintelligent/acp:latest

WORKDIR /app
# TODO: copy task fixtures into /app (COPY) and, if the task needs
# long-running services, add entrypoint.sh and use it as ENTRYPOINT.
# 'shlepa run' starts the container with a sleep-infinity command, so
# services must be started by the entrypoint before it blocks.
"""

TEST_OUTPUTS_PY = '''\
"""Verifier skeleton for {name} (pytest fallback path).

Replace the placeholder with real assertions on the agent's output in
the task workdir. Note: the faithful contest verifier is tests/test.sh
writing /logs/verifier/reward.txt; pytest files are the fallback used
by 'shlepa run' when tests/test.sh is absent.
"""


def test_outputs():
    assert True, "TODO: assert task outputs"
'''


def parse_task_name(name: str) -> tuple[str, str]:
    """Split ``<source>-<slug>`` into (source, display name).

    ``own-my-task`` -> ``("own", "own/my-task")``.
    Raises TaskNameError for invalid names or unknown sources.
    """
    if not NAME_RE.match(name):
        raise TaskNameError(
            f"invalid task name {name!r}: must match {NAME_RE.pattern} "
            "(lowercase alphanumeric segments joined by hyphens, at least two)"
        )
    source = name.split("-", 1)[0]
    if source not in KNOWN_SOURCES:
        raise TaskNameError(
            f"unknown source prefix {source!r} (expected one of: "
            + ", ".join(KNOWN_SOURCES)
            + ")"
        )
    return source, name.replace("-", "/", 1)


def scaffold(task_root: Path, name: str) -> Path:
    """Create ``tasks/<name>/`` from the template; return its path.

    Raises TaskNameError for invalid names and FileExistsError if the
    target directory already exists.
    """
    source, display = parse_task_name(name)
    task_root = Path(task_root)
    task_dir = task_root / name
    if task_dir.exists():
        raise FileExistsError(f"task directory already exists: {task_dir}")

    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "tests").mkdir()
    (task_dir / "solution").mkdir()
    (task_dir / "task.toml").write_text(
        TASK_TOML.format(source=source, display=display)
    )
    (task_dir / "instruction.md").write_text(INSTRUCTION_MD)
    (task_dir / "environment" / "Dockerfile").write_text(DOCKERFILE)
    (task_dir / "tests" / "test_outputs.py").write_text(
        TEST_OUTPUTS_PY.format(name=name)
    )
    (task_dir / "solution" / ".gitkeep").write_text("")
    return task_dir
