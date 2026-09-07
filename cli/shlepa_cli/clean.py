"""tmp/ workspace cleanup for 'shlepa clean'.

Run workspaces live in tmp/<timestamp>-<slug>/; this removes entries
older than the cutoff, always keeping tmp/README.md.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

DEFAULT_MAX_AGE_DAYS = 7


def clean(
    tmp_dir: Path,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    now: float | None = None,
) -> list[Path]:
    """Remove tmp/ entries older than ``max_age_days``; return removed paths.

    ``now`` is injectable for tests (time.time() by default). A missing
    tmp/ directory is not an error.
    """
    tmp_dir = Path(tmp_dir)
    if not tmp_dir.is_dir():
        return []
    now = time.time() if now is None else now
    max_age = max_age_days * 86400
    removed: list[Path] = []
    for entry in sorted(tmp_dir.iterdir()):
        if entry.name == "README.md":
            continue
        if now - entry.stat().st_mtime <= max_age:
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
        removed.append(entry)
    return removed


# Experiments whose runs are never touched by reconciliation: CI-owned
# (fixed experiment override) and telemetry/registry stores that carry
# no dev-run task runs at all.
NEVER_RECONCILE_EXPERIMENTS = {
    "shlepa-ci",
    "smoke",
    "shlepa-traces",
    "shlepa-submissions",
}


def reconcile_orphan_runs(client) -> list[str]:
    """Close dev-run task runs stuck in PENDING/RUNNING (any batch).

    Global reconciliation for ``shlepa clean --reconcile`` (backlog #35):
    a ``kill -9`` on a batch process cannot run the per-batch sweep, so
    orphans from previous batches accumulate and pollute batch analysis.
    Closes every run that (a) is in a dev (non-CI) experiment, (b) is
    still PENDING or RUNNING, and (c) carries a ``batch_id`` tag (the
    marker of a dev-run engine task run; manual/CI runs are untouched).
    Closed runs are marked FAILED with a ``termination_reason`` tag.
    Never raises: a reconciliation failure must not break ``clean``.
    """
    from shlepa_cli.run_engine import _close_run_failed

    closed: list[str] = []
    try:
        open_statuses = ("PENDING", "RUNNING")
        for experiment in client.search_experiments():
            if experiment.name in NEVER_RECONCILE_EXPERIMENTS:
                continue
            try:
                runs = client.search_runs(
                    experiment_ids=[experiment.experiment_id], max_results=1000
                )
            except Exception:  # noqa: BLE001 - keep sweeping the rest
                continue
            for run in runs:
                if run.info.status not in open_statuses:
                    continue
                if not run.data.tags.get("batch_id"):
                    continue
                _close_run_failed(
                    client,
                    run.info.run_id,
                    "orphaned: still open, closed by `shlepa clean --reconcile`",
                )
                closed.append(run.info.run_id)
    except Exception:  # noqa: BLE001 - reconciliation must never break clean
        pass
    return closed
