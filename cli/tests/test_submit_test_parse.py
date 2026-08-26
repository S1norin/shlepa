"""Tests for submit_test: Harbor job result parsing (fixture JSON)."""

import json
from pathlib import Path

from shlepa_cli import submit_test


def _write_job_result(path: Path, trial_results: list[dict]) -> Path:
    payload = {
        "id": "00000000-0000-0000-0000-000000000000",
        "started_at": "2026-08-26T12:00:00Z",
        "n_total_trials": len(trial_results),
        "stats": {"n_completed_trials": len(trial_results)},
        "trial_results": trial_results,
    }
    path.write_text(json.dumps(payload))
    return path


def _trial(
    task="contest-hello-file",
    *,
    solved=True,
    exception=None,
    tokens_in=10,
    tokens_out=5,
    started="2026-08-26T12:00:00Z",
    finished="2026-08-26T12:01:30Z",
):
    rewards = {"reward": 1 if solved else 0}
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "task_name": task,
        "trial_name": f"{task}-0",
        "trial_uri": "file:///x",
        "task_id": {"type": "local", "path": f"tasks/{task}"},
        "task_checksum": "abc",
        "config": {},
        "agent_info": {"name": "local-openrouter-agent", "version": "1"},
        "agent_result": {
            "n_input_tokens": tokens_in,
            "n_output_tokens": tokens_out,
        },
        # a trial that raised never reaches the verifier
        "verifier_result": None if exception is not None else {"rewards": rewards},
        "exception_info": exception,
        "started_at": started,
        "finished_at": finished,
    }


def test_parse_solved_trial(tmp_path):
    path = _write_job_result(tmp_path / "result.json", [_trial(solved=True)])
    trials = submit_test.parse_job_result(path)
    assert len(trials) == 1
    t = trials[0]
    assert t.task_name == "contest-hello-file"
    assert t.status == "solved"
    assert t.reward == 1
    assert t.tokens_in == 10
    assert t.tokens_out == 5
    assert t.duration_sec == 90.0
    assert t.error is None


def test_parse_unsolved_trial(tmp_path):
    path = _write_job_result(tmp_path / "result.json", [_trial(solved=False)])
    t = submit_test.parse_job_result(path)[0]
    assert t.status == "unsolved"
    assert t.reward == 0


def test_parse_timeout_trial(tmp_path):
    exc = {
        "exception_type": "TimeoutError",
        "exception_message": "Agent timed out after 300s",
        "exception_traceback": "...",
        "occurred_at": "2026-08-26T12:05:00Z",
    }
    path = _write_job_result(tmp_path / "result.json", [_trial(exception=exc)])
    t = submit_test.parse_job_result(path)[0]
    assert t.status == "timeout"
    assert "TimeoutError" in t.error
    assert t.reward is None


def test_parse_error_trial(tmp_path):
    exc = {
        "exception_type": "RuntimeError",
        "exception_message": "docker build failed",
        "exception_traceback": "...",
        "occurred_at": "2026-08-26T12:05:00Z",
    }
    path = _write_job_result(tmp_path / "result.json", [_trial(exception=exc)])
    t = submit_test.parse_job_result(path)[0]
    assert t.status == "error"
    assert "docker build failed" in t.error


def test_parse_missing_verifier_and_tokens(tmp_path):
    trial = _trial()
    trial["verifier_result"] = None
    trial["agent_result"] = None
    path = _write_job_result(tmp_path / "result.json", [trial])
    t = submit_test.parse_job_result(path)[0]
    assert t.status == "unsolved"  # no reward -> not solved
    assert t.reward is None
    assert t.tokens_in is None
    assert t.tokens_out is None


def test_parse_empty_job(tmp_path):
    path = _write_job_result(tmp_path / "result.json", [])
    assert submit_test.parse_job_result(path) == []


def test_parse_missing_file(tmp_path):
    try:
        submit_test.parse_job_result(tmp_path / "nope.json")
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError:
        pass
