"""Tests for the run-state file location (#62): never in the workdir."""

import json
from types import SimpleNamespace

from shlepa_agent.state import DEFAULT_STATE_PATH, save_state


def _state(workdir):
    return SimpleNamespace(
        deps=SimpleNamespace(workdir=workdir, budget=None),
        model=SimpleNamespace(elapsed=lambda: 1.2),
        cycles=1,
        results={},
    )


def test_state_file_never_written_to_workdir(tmp_path):
    save_state(_state(tmp_path))
    assert list(tmp_path.iterdir()) == []  # workdir stays clean


def test_state_file_defaults_to_tmp(tmp_path):
    assert str(DEFAULT_STATE_PATH).startswith("/tmp/")
    try:
        save_state(_state(tmp_path))
        assert DEFAULT_STATE_PATH.exists()
        data = json.loads(DEFAULT_STATE_PATH.read_text(encoding="utf-8"))
        assert data["cycles"] == 1
        assert data["elapsed"] == 1.2
    finally:
        if DEFAULT_STATE_PATH.exists():
            DEFAULT_STATE_PATH.unlink()


def test_state_file_env_override(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    monkeypatch.setenv("SHLEPA_STATE_FILE", str(target))
    save_state(_state(tmp_path))
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["cycles"] == 1
    assert list(tmp_path.iterdir()) == [target]  # not in the workdir


def test_state_file_missing_parent_dir_is_swallowed(tmp_path, monkeypatch):
    target = tmp_path / "no" / "such" / "dir" / "state.json"
    monkeypatch.setenv("SHLEPA_STATE_FILE", str(target))
    save_state(_state(tmp_path))  # must not raise
    assert not target.exists()
