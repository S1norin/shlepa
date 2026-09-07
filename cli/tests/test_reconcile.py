"""Tests for `shlepa clean --reconcile` (backlog #35: global orphan run
reconciliation for killed batch processes)."""

import pytest
from mlflow import MlflowClient


@pytest.fixture(autouse=True)
def _allow_file_store(monkeypatch):
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")


def _client(tmp_path):
    return MlflowClient(tracking_uri=f"file://{tmp_path / 'mlstore'}")


def _open_run(client, experiment_id, run_name, tags=None):
    """Create a run and leave it open (PENDING/RUNNING)."""
    run = client.create_run(experiment_id=experiment_id, run_name=run_name, tags=tags or {})
    return run.info.run_id


def test_reconcile_closes_dev_orphans_only(tmp_path):
    from shlepa_cli.clean import reconcile_orphan_runs

    client = _client(tmp_path)
    dev_exp = client.create_experiment("bench-dev")
    ci_exp = client.create_experiment("shlepa-ci")

    dev_orphan = _open_run(
        client, dev_exp, "task-a", tags={"batch_id": "20260901-000000-aaaaaa"}
    )
    dev_orphan2 = _open_run(
        client, dev_exp, "task-b", tags={"batch_id": "20260902-000000-bbbbbb"}
    )
    ci_orphan = _open_run(
        client, ci_exp, "ci-task", tags={"batch_id": "20260903-000000-cccccc"}
    )
    manual_run = _open_run(client, dev_exp, "manual-task", tags={"note": "manual"})
    # A finished dev batch run must not be touched.
    done_run = _open_run(
        client, dev_exp, "done-task", tags={"batch_id": "20260904-000000-dddddd"}
    )
    client.set_terminated(done_run, status="FINISHED")

    closed = reconcile_orphan_runs(client)

    assert sorted(closed) == sorted([dev_orphan, dev_orphan2])
    for rid in (dev_orphan, dev_orphan2):
        run = client.get_run(rid)
        assert run.info.status == "FAILED"
        assert "reconcile" in run.data.tags["termination_reason"]
    # CI-owned experiment and manual (no batch_id) runs stay untouched.
    assert client.get_run(ci_orphan).info.status in ("PENDING", "RUNNING")
    assert client.get_run(manual_run).info.status in ("PENDING", "RUNNING")
    assert client.get_run(done_run).info.status == "FINISHED"


def test_reconcile_idempotent_and_empty(tmp_path):
    from shlepa_cli.clean import reconcile_orphan_runs

    client = _client(tmp_path)
    dev_exp = client.create_experiment("bench-dev")
    orphan = _open_run(client, dev_exp, "task-a", tags={"batch_id": "b1"})

    assert reconcile_orphan_runs(client) == [orphan]
    # Second pass: nothing left to close.
    assert reconcile_orphan_runs(client) == []
    assert reconcile_orphan_runs(client) == []


def test_reconcile_never_raises_on_broken_client(tmp_path):
    from shlepa_cli.clean import reconcile_orphan_runs

    class _Broken:
        def search_experiments(self):
            raise RuntimeError("tracking store down")

    assert reconcile_orphan_runs(_Broken()) == []
