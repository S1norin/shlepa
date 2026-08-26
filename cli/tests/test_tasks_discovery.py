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


def test_discover_parses_verifier_env_and_timeout(tmp_path):
    root = tmp_path / "repo"
    _write(
        root / "tasks" / "contest-hello-file" / "task.toml",
        """
schema_version = "1.2"
name = "Hello File"

[verifier]
timeout_sec = 90

[verifier.env]
API_TOKEN = "abc"

[environment.env]
APP_PORT = "8080"
""",
    )

    found = tasks.discover_tasks(root / "tasks")

    assert len(found) == 1
    hello = found[0]
    assert hello.verifier_env == {"API_TOKEN": "abc"}
    assert hello.verifier_timeout_sec == 90
    assert hello.env == {"APP_PORT": "8080"}


def test_discover_verifier_sections_optional(tmp_path):
    root = tmp_path / "repo"
    _write(
        root / "tasks" / "contest-bye-file" / "task.toml",
        'schema_version = "1.2"\nname = "Bye File"\n',
    )

    found = tasks.discover_tasks(root / "tasks")

    assert found[0].verifier_env == {}
    assert found[0].verifier_timeout_sec is None


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


def test_discover_prefers_task_section_name(tmp_path):
    """Contest schema 1.2 puts the display name in [task].name."""
    root = tmp_path / "repo"
    _write(
        root / "tasks" / "contest-hello-file" / "task.toml",
        """
schema_version = "1.2"
name = "legacy-top-level"

[task]
name = "local/hello-file"
""",
    )

    found = tasks.discover_tasks(root / "tasks")

    assert found[0].name == "local/hello-file"


def test_discover_name_falls_back_to_directory(tmp_path):
    root = tmp_path / "repo"
    _write(
        root / "tasks" / "own-no-name" / "task.toml",
        'schema_version = "1.2"\n',
    )

    found = tasks.discover_tasks(root / "tasks")

    assert found[0].name == "own-no-name"
