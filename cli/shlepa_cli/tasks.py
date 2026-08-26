"""Task discovery and experiment presets.

Tasks live in a flat layout: ``tasks/<slug>/task.toml`` (Harbor format).
Presets live in ``experiments/<name>.yaml``.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Task:
    """A discovered task directory."""

    slug: str
    name: str
    path: Path
    difficulty: str | None = None
    timeout_sec: int | None = None


@dataclass(frozen=True)
class Preset:
    """An experiment preset (experiments/<name>.yaml)."""

    name: str
    tasks: str | list[str]  # 'all' or a list of slugs
    model: str | None = None
    agent: dict = field(default_factory=dict)


def discover_tasks(tasks_dir: Path) -> list[Task]:
    """Scan ``tasks_dir/*/task.toml`` and return tasks sorted by slug.

    Directories without a task.toml are ignored.
    """
    tasks_dir = Path(tasks_dir)
    if not tasks_dir.is_dir():
        raise ValueError(f"tasks directory not found: {tasks_dir}")
    found: list[Task] = []
    for entry in sorted(tasks_dir.iterdir()):
        manifest = entry / "task.toml"
        if not entry.is_dir() or not manifest.is_file():
            continue
        data = tomllib.loads(manifest.read_text())
        metadata = data.get("metadata", {})
        agent = data.get("agent", {})
        found.append(
            Task(
                slug=entry.name,
                name=data.get("name", entry.name),
                path=entry,
                difficulty=metadata.get("difficulty"),
                timeout_sec=agent.get("timeout_sec"),
            )
        )
    return found


def load_preset(path: Path) -> Preset:
    """Load a preset YAML file into a Preset."""
    data = yaml.safe_load(Path(path).read_text()) or {}
    if "name" not in data or "tasks" not in data:
        raise ValueError(
            f"preset {path} must define 'name' and 'tasks'"
        )
    return Preset(
        name=data["name"],
        tasks=data["tasks"],
        model=data.get("model"),
        agent=dict(data.get("agent") or {}),
    )


def load_preset_by_name(repo_root: Path, name: str) -> Preset:
    """Load experiments/<name>.yaml from the repo root.

    Raises FileNotFoundError listing the available presets.
    """
    path = Path(repo_root) / "experiments" / f"{name}.yaml"
    if not path.is_file():
        presets_dir = Path(repo_root) / "experiments"
        available = (
            sorted(p.stem for p in presets_dir.glob("*.yaml"))
            if presets_dir.is_dir()
            else []
        )
        raise FileNotFoundError(
            f"preset {name!r} not found at {path}; "
            f"available presets: {', '.join(available) or 'none'}"
        )
    return load_preset(path)


def resolve_tasks(preset: Preset, all_tasks: list[Task]) -> list[Task]:
    """Resolve a preset's task list against the discovered tasks.

    ``tasks: 'all'`` selects every discovered task. Unknown slugs raise
    ValueError listing the valid ones.
    """
    if preset.tasks == "all":
        return list(all_tasks)
    by_slug = {t.slug: t for t in all_tasks}
    resolved = []
    unknown = []
    for slug in preset.tasks:
        if slug in by_slug:
            resolved.append(by_slug[slug])
        else:
            unknown.append(slug)
    if unknown:
        valid = ", ".join(sorted(by_slug)) or "none"
        raise ValueError(
            f"unknown task(s) in preset {preset.name!r}: "
            f"{', '.join(unknown)}; valid slugs: {valid}"
        )
    return resolved
