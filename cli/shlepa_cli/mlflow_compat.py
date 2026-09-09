"""Compatibility wrappers for MLflow client APIs.

MLflow 3.15 deprecated ``search_traces(experiment_ids=...)`` in favor of
``locations=...``, but the ``locations`` form hangs on the current remote
server (MLflow 3.15.1). All calls that must use the deprecated form go
through this module so the cutover is a one-file change: switch the
argument here, everything else keeps working.
"""

from __future__ import annotations

import warnings


def search_experiment_traces(
    client,
    experiment_id: str,
    max_results: int,
    filter_string: str | None = None,
    include_spans: bool = True,
):
    """``client.search_traces`` over one experiment, warnings contained.

    Uses the deprecated ``experiment_ids`` form (see module docstring)
    and suppresses the resulting ``FutureWarning`` so callers do not
    need to manage the warning filter themselves.

    The remote server is 50-100x slower when span payloads are fetched
    in the search (``include_spans=False``), so pass ``False`` when only
    trace-level fields (id, tags, request_time) are needed, and a
    ``filter_string`` (e.g. a ``timestamp_ms >=`` window) whenever one
    is known — an unfiltered search takes minutes.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        kwargs = {
            "experiment_ids": [str(experiment_id)],
            "max_results": max_results,
        }
        if filter_string is not None:
            kwargs["filter_string"] = filter_string
        if not include_spans:
            kwargs["include_spans"] = False
        return client.search_traces(**kwargs)
