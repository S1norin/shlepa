"""mlflow_compat: deprecated-API shims with contained warnings."""

from __future__ import annotations

import warnings

from shlepa_cli import mlflow_compat as compat


class _FakeTrace:
    def __init__(self, trace_id):
        self.info = type("Info", (), {"trace_id": trace_id, "tags": {}})()


class _FakeClient:
    def __init__(self, result=None, warn=False):
        self.calls = []
        self.result = result if result is not None else [_FakeTrace("t1")]
        self.warn = warn

    def search_traces(self, **kwargs):
        self.calls.append(kwargs)
        if self.warn:
            warnings.warn(
                "experiment_ids is deprecated", FutureWarning, stacklevel=2
            )
        return self.result


def test_uses_deprecated_experiment_ids_form():
    client = _FakeClient()
    compat.search_experiment_traces(client, "21", 500)
    assert client.calls == [{"experiment_ids": ["21"], "max_results": 500}]
    assert "locations" not in client.calls[0]


def test_future_warning_does_not_leak_to_caller():
    client = _FakeClient(warn=True)
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        result = compat.search_experiment_traces(client, "21", 50)
    assert result is client.result


def test_no_direct_search_traces_calls_outside_shim():
    # gate: every call site goes through the shim, so the locations=
    # cutover stays a one-file change
    from pathlib import Path

    package_dir = Path(compat.__file__).resolve().parent
    offenders = []
    for path in sorted(package_dir.glob("*.py")):
        if path.name == "mlflow_compat.py":
            continue
        source = path.read_text()
        if ".search_traces(" in source:
            offenders.append(path.name)
    assert offenders == []
