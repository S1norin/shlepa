"""Task discovery tests (fixture tree)."""

from shlepa_cli import tasks


def _write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_discover_parses_task_toml(tmp_path):
    root = tmp_path / "repo"
    _write(
        root / "tasks" / "contest-hello-file" / "task.toml",
        """
schema_version = "1.2"
name = "Hello File"

[metadata]
difficulty = "easy"
source = "contest"

[agent]
timeout_sec = 300
""",
    )
    _write(
        root / "tasks" / "contest-bye-file" / "task.toml",
        'schema_version = "1.2"\nname = "Bye File"\n',
    )
    _write(root / "tasks" / "not-a-task" / "README.md", "no task.toml here\n")
    (root / "tasks" / "empty-dir").mkdir(parents=True)

    found = tasks.discover_tasks(root / "tasks")

    assert [t.slug for t in found] == ["contest-bye-file", "contest-hello-file"]
    hello = next(t for t in found if t.slug == "contest-hello-file")
    assert hello.name == "Hello File"
    assert hello.difficulty == "easy"
    assert hello.timeout_sec == 300
    bye = next(t for t in found if t.slug == "contest-bye-file")
    assert bye.difficulty is None
    assert bye.timeout_sec is None
    assert hello.path == root / "tasks" / "contest-hello-file"


def test_discover_empty_dir(tmp_path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    assert tasks.discover_tasks(tasks_dir) == []


def test_discover_missing_dir_raises(tmp_path):
    try:
        tasks.discover_tasks(tmp_path / "nope")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
