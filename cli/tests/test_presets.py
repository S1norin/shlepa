"""Preset loader and resolution tests."""

import pytest

from shlepa_cli import tasks


def _write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _repo_with_tasks(root):
    _write(
        root / "tasks" / "contest-hello-file" / "task.toml",
        'schema_version = "1.2"\nname = "Hello File"\n',
    )
    _write(
        root / "tasks" / "contest-bye-file" / "task.toml",
        'schema_version = "1.2"\nname = "Bye File"\n',
    )
    return tasks.discover_tasks(root / "tasks")


def test_load_preset_full(tmp_path):
    path = tmp_path / "presets" / "quick.yaml"
    _write(
        path,
        "name: quick\ntasks: [contest-hello-file, contest-bye-file]\n"
        "model: gpt-4o-mini\nagent:\n  max_tokens: 2048\n",
    )
    preset = tasks.load_preset(path)
    assert preset.name == "quick"
    assert preset.tasks == ["contest-hello-file", "contest-bye-file"]
    assert preset.model == "gpt-4o-mini"
    assert preset.agent == {"max_tokens": 2048}


def test_load_preset_requires_name_and_tasks(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("model: gpt-4o-mini\n")
    with pytest.raises(ValueError, match="name.*tasks"):
        tasks.load_preset(path)


def test_load_preset_by_name_missing_lists_available(tmp_path):
    (tmp_path / "experiments").mkdir()
    (tmp_path / "experiments" / "all.yaml").write_text("name: all\ntasks: all\n")
    with pytest.raises(FileNotFoundError, match="all"):
        tasks.load_preset_by_name(tmp_path, "nope")


def test_resolve_all(tmp_path):
    all_tasks = _repo_with_tasks(tmp_path)
    preset = tasks.Preset(name="all", tasks="all")
    assert [t.slug for t in tasks.resolve_tasks(preset, all_tasks)] == [
        "contest-bye-file",
        "contest-hello-file",
    ]


def test_resolve_subset(tmp_path):
    all_tasks = _repo_with_tasks(tmp_path)
    preset = tasks.Preset(name="quick", tasks=["contest-hello-file"])
    resolved = tasks.resolve_tasks(preset, all_tasks)
    assert [t.slug for t in resolved] == ["contest-hello-file"]


def test_resolve_unknown_slug_lists_valid(tmp_path):
    all_tasks = _repo_with_tasks(tmp_path)
    preset = tasks.Preset(name="bad", tasks=["contest-missing"])
    with pytest.raises(ValueError, match="contest-missing"):
        tasks.resolve_tasks(preset, all_tasks)
    with pytest.raises(ValueError) as excinfo:
        tasks.resolve_tasks(preset, all_tasks)
    assert "contest-hello-file" in str(excinfo.value)


def test_shipped_all_yaml(tmp_path):
    # The repo ships experiments/all.yaml.
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[2]
    shipped = repo_root / "experiments" / "all.yaml"
    assert shipped.is_file(), "experiments/all.yaml is not shipped"
    preset = tasks.load_preset(shipped)
    assert preset.name == "all"
    assert preset.tasks == "all"
