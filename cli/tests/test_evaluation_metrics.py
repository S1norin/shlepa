"""Measurement semantics: invalid grading, partial usage, and comparable batches."""

import json
import logging
from pathlib import Path

import pytest
from mlflow import MlflowClient

from shlepa_cli.evaluation import reward_grade, pytest_grade, summarize_batches
from shlepa_cli.metrics_capture import MetricsCapture
from shlepa_cli import run_engine
from test_run_engine_container import FakeDocker, _repo, _settings


@pytest.mark.parametrize("text", ["", "NaN", "inf", "-1", "1.1", "broken"])
def test_invalid_reward_is_not_a_measured_failure(text):
    grade = reward_grade(text, "details")
    assert not grade.valid
    assert grade.reward is None
    assert grade.status == "invalid_reward"


@pytest.mark.parametrize(
    "text,reward,solved", [("1.0", 1, True), ("0.5", 0.5, False), ("0", 0, False)]
)
def test_numeric_reward_and_assertion_exit(text, reward, solved):
    grade = reward_grade(text, "details", returncode=1)
    assert grade.valid and grade.reward == reward and grade.solved == solved


def test_pytest_collection_failure_is_invalid():
    assert not pytest_grade(2, "collection error").valid
    assert not pytest_grade(5, "no tests").valid
    assert pytest_grade(1, "assertion failed").reward == 0


def test_container_partial_reward_and_timing(tmp_path):
    result = run_engine.run_task(
        _repo(tmp_path),
        _settings(tmp_path),
        model="test",
        no_docker=False,
        docker_client=FakeDocker(reward="0.5"),
    )
    assert result.evaluation_valid and result.reward == 0.5 and not result.solved
    assert set(result.timings) == {
        "setup_duration_sec",
        "agent_duration_sec",
        "grader_duration_sec",
    }
    assert all(value >= 0 for value in result.timings.values())
    assert result.provenance["task_hash"] and result.provenance["grader_hash"]
    assert json.loads((result.workspace / "result.json").read_text())["reward"] == 0.5


def test_grader_exception_preserves_agent_usage(tmp_path):
    class BrokenGrader(FakeDocker):
        def exec(self, name, cmd, env=None, timeout=None):
            if cmd == ["bash", "/tests/test.sh"]:
                raise RuntimeError("verifier unavailable")
            return super().exec(name, cmd, env, timeout)

    result = run_engine.run_task(
        _repo(tmp_path),
        _settings(tmp_path),
        model="test",
        no_docker=False,
        docker_client=BrokenGrader(),
    )
    assert not result.evaluation_valid
    assert result.grader_status == "grader_error"
    assert result.tokens_in == 4 and result.tokens_out == 2
    assert result.termination == "ok"
    assert "grader_duration_sec" in result.timings


def test_capture_retries_reasoning_and_missing_usage():
    capture = MetricsCapture()
    for data in [
        {"event": "llm_request"},
        {"event": "llm_error"},
        {"event": "llm_retry"},
        {"event": "llm_request"},
        {"event": "usage", "cumulative_input": 10, "cumulative_output": 8, "reasoning_tokens": 3},
        {"event": "tool_completed", "tool": "bash", "duration_sec": 2, "failed": True},
        {"event": "tool_result", "exit_code": "timeout"},
        {"event": "llm_tool_result", "validation_retry": True},
    ]:
        capture.emit(logging.makeLogRecord({"msg": json.dumps(data)}))
    snapshot = capture.snapshot()
    metrics = snapshot["measurements"]
    assert metrics["llm_requests"] == 2 and metrics["llm_retries"] == 1
    assert metrics["llm_errors"] == 1 and metrics["usage_reports"] == 1
    assert metrics["tokens_reasoning"] == 3 and capture.tokens_out == 8
    assert metrics["tool_errors"] == 1 and metrics["tool_timeouts"] == 1
    assert metrics["tool_validation_retries"] == 1
    assert snapshot["usage_status"] == "partial"
    assert snapshot["cache_usage_status"] == "unknown"
    assert "tokens_reasoning" not in MetricsCapture().snapshot()["measurements"]


def test_run_is_created_before_execution_and_closed_on_interrupt(tmp_path, monkeypatch):
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    client = MlflowClient(tracking_uri=f"file://{tmp_path / 'store'}")
    from shlepa_cli.tasks import Preset

    def interrupted(*args, **kwargs):
        exp = client.get_experiment_by_name("contest")
        runs = client.search_runs([exp.experiment_id])
        assert len(runs) == 1 and runs[0].info.status == "RUNNING"
        assert runs[0].data.tags["execution_id"] == kwargs["execution_id"]
        raise KeyboardInterrupt()

    monkeypatch.setattr(run_engine, "run_task", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_engine.run_preset(
            _settings(tmp_path),
            Preset("all", "all"),
            [_repo(tmp_path)],
            model="test",
            mlflow_client=client,
        )
    exp = client.get_experiment_by_name("contest")
    assert client.search_runs([exp.experiment_id])[0].info.status == "FAILED"


def test_summary_keeps_invalid_trials_visible_and_separates_models(tmp_path, monkeypatch):
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    client = MlflowClient(tracking_uri=f"file://{tmp_path / 'store'}")
    exp = client.create_experiment("contest")
    for model, valid, solved, reward in [("a", 1, 1, 1), ("a", 0, 0, None), ("b", 1, 0, 0)]:
        run_id = client.create_run(
            exp, tags={"run_kind": "trial", "batch_id": "batch-1", "model": model, "task": "task-1"}
        ).info.run_id
        client.log_metric(run_id, "evaluation_valid", valid)
        client.log_metric(run_id, "solved", solved)
        if reward is not None:
            client.log_metric(run_id, "reward", reward)
        client.set_terminated(run_id)
    ids = summarize_batches(client, ["batch-1"])
    assert len(ids) == 2
    runs = {client.get_run(i).data.tags["model"]: client.get_run(i) for i in ids}
    assert runs["a"].data.metrics["invalid_attempts"] == 1
    assert runs["a"].data.metrics["success_rate"] == 1
    assert runs["b"].data.metrics["success_rate"] == 0
    artifact = client.download_artifacts(runs["a"].info.run_id, "summary.json")
    assert len(json.loads(Path(artifact).read_text())["source_run_ids"]) == 2
