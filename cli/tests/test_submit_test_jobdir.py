"""Tests for submit_test: job-dir discovery + trial-directory parsing."""

import json

from shlepa_cli import submit_test


def _trial_result(task_name="local/hello-file", *, reward=1.0):
    return {
        "id": "22222222-2222-2222-2222-222222222222",
        "task_name": task_name,
        "trial_name": f"{task_name}-0",
        "trial_uri": "file:///x",
        "task_id": {"type": "local", "path": "tasks/contest-hello-file"},
        "source": None,
        "task_checksum": "abc",
        "config": {},
        "agent_info": {"name": "local-openrouter-agent", "version": "unknown"},
        "agent_result": {"n_input_tokens": None, "n_output_tokens": None},
        "verifier_result": {"rewards": {"reward": reward}},
        "exception_info": None,
        "started_at": "2026-08-26T16:04:50.546769Z",
        "finished_at": "2026-08-26T16:05:47.920424Z",
    }


def _job_level(trial_results: list | None):
    payload = {
        "id": "33333333-3333-3333-3333-333333333333",
        "started_at": "2026-08-26T16:04:00Z",
        "n_total_trials": len(trial_results) if trial_results else 1,
        "stats": {"n_completed_trials": len(trial_results or [])},
    }
    if trial_results is not None:
        payload["trial_results"] = trial_results
    return payload


def test_find_job_dir_exact(tmp_path):
    job_dir = tmp_path / "jobs" / "job-1"
    job_dir.mkdir(parents=True)
    (job_dir / "result.json").write_text("{}")
    found = submit_test.find_job_dir(tmp_path / "jobs", "job-1")
    assert found == job_dir


def test_find_job_dir_single_candidate_fallback(tmp_path):
    other = tmp_path / "jobs" / "some-job"
    other.mkdir(parents=True)
    (other / "result.json").write_text("{}")
    found = submit_test.find_job_dir(tmp_path / "jobs", "renamed-job")
    assert found == other


def test_find_job_dir_missing_raises(tmp_path):
    (tmp_path / "jobs").mkdir()
    try:
        submit_test.find_job_dir(tmp_path / "jobs", "nope")
        raise AssertionError("expected JobDirNotFound")
    except submit_test.JobDirNotFound:
        pass


def test_parse_job_dir_trial_subdirs(tmp_path):
    job_dir = tmp_path / "j"
    (job_dir / "contest-hello-file__abc").mkdir(parents=True)
    (job_dir / "contest-hello-file__abc" / "result.json").write_text(
        json.dumps(_trial_result(reward=1.0))
    )
    (job_dir / "contest-bye-file__def").mkdir()
    (job_dir / "contest-bye-file__def" / "result.json").write_text(
        json.dumps(_trial_result(task_name="local/bye-file", reward=0.0))
    )
    # job-level result.json without embedded trial_results (current Harbor)
    (job_dir / "result.json").write_text(json.dumps(_job_level(None)))

    trials = submit_test.parse_job_dir(job_dir)
    assert [t.task_name for t in trials] == ["local/bye-file", "local/hello-file"]
    by_task = {t.task_name: t for t in trials}
    assert by_task["local/hello-file"].status == "solved"
    assert by_task["local/hello-file"].reward == 1.0
    assert by_task["local/bye-file"].status == "unsolved"
    assert by_task["local/hello-file"].tokens_in is None
    assert by_task["local/hello-file"].duration_sec is not None


def test_parse_job_dir_prefers_embedded_trials(tmp_path):
    job_dir = tmp_path / "j"
    job_dir.mkdir()
    (job_dir / "result.json").write_text(
        json.dumps(_job_level([_trial_result()]))
    )
    trials = submit_test.parse_job_dir(job_dir)
    assert len(trials) == 1
    assert trials[0].status == "solved"


def test_parse_job_dir_empty(tmp_path):
    job_dir = tmp_path / "j"
    job_dir.mkdir()
    (job_dir / "result.json").write_text(json.dumps(_job_level(None)))
    assert submit_test.parse_job_dir(job_dir) == []
