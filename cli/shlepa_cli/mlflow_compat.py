"""Compatibility wrappers for MLflow client APIs.

MLflow 3.15 deprecated ``search_traces(experiment_ids=...)`` in favor of
``locations=...``, but the ``locations`` form hangs on the current remote
server (MLflow 3.15.1). All calls that must use the deprecated form go
through this module so the cutover is a one-file change: switch the
argument here, everything else keeps working.
"""

from __future__ import annotations

import warnings


def search_experiment_traces(client, experiment_id: str, max_results: int):
    """``client.search_traces`` over one experiment, warnings contained.

    Uses the deprecated ``experiment_ids`` form (see module docstring)
    and suppresses the resulting ``FutureWarning`` so callers do not
    need to manage the warning filter themselves.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        return client.search_traces(
            experiment_ids=[str(experiment_id)], max_results=max_results
        )
