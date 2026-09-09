"""Evaluation semantics and reproducible metadata for agent trials."""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class Grade:
    solved: bool
    detail: str
    reward: float | None = None
    valid: bool = False
    status: str = "not_run"

    def __iter__(self):
        # Retain unpacking compatibility for existing scorer callers.
        yield self.solved
        yield self.detail


def reward_grade(content: str, detail: str, returncode: int = 0) -> Grade:
    try:
        reward = float(content.strip())
        if not math.isfinite(reward) or not 0 <= reward <= 1:
            raise ValueError("reward outside [0, 1]")
    except ValueError:
        return Grade(False, detail, status="invalid_reward")
    # A verifier may exit nonzero for failed assertions while emitting a valid reward.
    return Grade(reward == 1, detail, reward, True, "scored")


def pytest_grade(returncode: int, detail: str) -> Grade:
    if returncode in (0, 1):
        return Grade(returncode == 0, detail, float(returncode == 0), True, "scored")
    return Grade(False, detail, status=f"pytest_exit_{returncode}")


def fingerprint(root: Path, paths) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        if (
            any(
                part in {"__pycache__", ".pytest_cache", ".venv", ".git"}
                for part in path.relative_to(root).parts
            )
            or path.suffix == ".pyc"
        ):
            continue
        if path.is_file() and not path.is_symlink():
            digest.update(str(path.relative_to(root)).encode() + b"\0")
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
    return digest.hexdigest()


def config_hash(configuration: dict) -> str:
    return hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()


def aggregate_trials(results) -> dict:
    """Task-balanced descriptive summary; invalid trials are reported separately.

    No independence-based confidence interval is fabricated for repeated tasks.
    Cost and latency remain measured per attempt; no missing value becomes zero.
    """
    valid = [r for r in results if r.evaluation_valid]
    tasks = {}
    for result in valid:
        tasks.setdefault(result.slug, []).append(result)
    return {
        "attempts": len(results),
        "valid_attempts": len(valid),
        "invalid_attempts": len(results) - len(valid),
        "tasks": len(tasks),
        "success_rate": sum(r.solved for r in valid) / len(valid) if valid else None,
        "task_macro_success_rate": (
            sum(sum(r.solved for r in group) / len(group) for group in tasks.values()) / len(tasks)
            if tasks
            else None
        ),
        "mean_reward": sum(r.reward for r in valid) / len(valid) if valid else None,
        "per_task": {
            slug: {"attempts": len(group), "successes": sum(r.solved for r in group)}
            for slug, group in tasks.items()
        },
    }


def summarize_batches(client, batch_ids: list[str]) -> list[str]:
    """Write summary runs for homogeneous configurations within each family.

    Source IDs are retained in an artifact. Re-running a summary creates a new
    analysis run, never changes or deletes a source trial.
    """
    from collections import defaultdict
    import re
    import tempfile
    from types import SimpleNamespace
    from shlepa_cli.mlflow_client import masked_client_stdout

    if not batch_ids or any(not re.fullmatch(r"[A-Za-z0-9_-]+", b) for b in batch_ids):
        raise ValueError("batch IDs must contain only letters, digits, underscores and hyphens")
    groups = defaultdict(list)
    for experiment in client.search_experiments():
        for batch_id in dict.fromkeys(batch_ids):
            token = None
            while True:
                page = client.search_runs(
                    [experiment.experiment_id],
                    filter_string=f"tags.batch_id = '{batch_id}' AND tags.run_kind = 'trial'",
                    max_results=1000,
                    page_token=token,
                )
                for run in page:
                    tags, params = run.data.tags, run.data.params
                    key = (
                        experiment.experiment_id,
                        tags.get("model"),
                        tags.get("git_sha"),
                        params.get("config_hash"),
                        tags.get("endpoint_class"),
                        tags.get("toolset"),
                        params.get("agent_source_hash"),
                        params.get("runner"),
                    )
                    groups[key].append(run)
                token = getattr(page, "token", None)
                if not token:
                    break
    if not groups:
        raise ValueError("no schema-v2 trial runs found for these batches")
    summary_ids = []
    for key, runs in groups.items():
        revisions = defaultdict(set)
        results = []
        for run in runs:
            metrics, tags, params = run.data.metrics, run.data.tags, run.data.params
            slug = tags.get("task", run.info.run_name)
            revisions[slug].add((params.get("task_hash"), params.get("grader_hash")))
            results.append(
                SimpleNamespace(
                    slug=slug,
                    solved=metrics.get("solved") == 1,
                    reward=metrics.get("reward"),
                    evaluation_valid=metrics.get("evaluation_valid") == 1 and "reward" in metrics,
                )
            )
        if any(len(values) > 1 for values in revisions.values()):
            raise ValueError(
                "task/grader revisions differ within a comparison; select compatible batches"
            )
        summary = aggregate_trials(results)
        durations = sorted(
            r.data.metrics["agent_duration_sec"]
            for r in runs
            if "agent_duration_sec" in r.data.metrics
        )
        summary["agent_duration_samples"] = len(durations)
        if durations:
            import statistics

            summary["agent_duration_p50_sec"] = statistics.median(durations)
            summary["agent_duration_p95_sec"] = durations[math.ceil(0.95 * len(durations)) - 1]
        summary["source_run_ids"] = [r.info.run_id for r in runs]
        summary["batch_ids"] = batch_ids
        with masked_client_stdout():
            summary_id = client.create_run(
                experiment_id=key[0],
                run_name="batch-summary",
                tags={
                    "run_kind": "batch_summary",
                    "metrics_schema_version": "2",
                    "model": key[1] or "unknown",
                    "git_sha": key[2] or "unknown",
                    "endpoint_class": key[4] or "unknown",
                    "toolset": key[5] or "unknown",
                },
            ).info.run_id
        try:
            client.log_param(summary_id, "config_hash", key[3] or "unknown")
            client.log_param(summary_id, "agent_source_hash", key[6] or "unknown")
            client.log_param(summary_id, "runner", key[7] or "unknown")
            for name, value in summary.items():
                if isinstance(value, (int, float)):
                    client.log_metric(summary_id, name, value)
            with tempfile.TemporaryDirectory(prefix="shlepa-summary-") as directory:
                path = Path(directory) / "summary.json"
                path.write_text(json.dumps(summary, indent=2))
                client.log_artifact(summary_id, str(path))
            client.set_terminated(summary_id, status="FINISHED")
        except BaseException:
            client.set_terminated(summary_id, status="FAILED")
            raise
        summary_ids.append(summary_id)
    return summary_ids
