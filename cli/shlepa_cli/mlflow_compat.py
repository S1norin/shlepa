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


def iter_experiment_traces(
    client,
    experiment_id: str,
    page_size: int,
    filter_string: str | None = None,
):
    """Yield every trace of one experiment, following pagination tokens.

    ``search_traces`` bounds a single call by ``max_results``; the
    MLflow 3.x result is a ``PagedList`` that carries the next-page
    ``token``. This walks all pages until a page comes back short, the
    token runs out, or a full page brings no new trace ids (a stuck
    token must not loop forever). ``filter_string`` (e.g. a
    ``timestamp_ms >= ...`` window) is passed through to the server; the
    caller still re-checks any client-side criteria, since the filter is
    only an optimization.

    Uses the deprecated ``experiment_ids`` form (see module docstring)
    with the resulting ``FutureWarning`` suppressed.
    """
    page_token = None
    seen: set[str] = set()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        while True:
            kwargs: dict = {
                "experiment_ids": [str(experiment_id)],
                "max_results": page_size,
            }
            if filter_string:
                kwargs["filter_string"] = filter_string
            if page_token is not None:
                kwargs["page_token"] = page_token
            page = client.search_traces(**kwargs)
            items = list(page)
            if not items:
                return
            new_items = 0
            for item in items:
                trace_id = getattr(getattr(item, "info", None), "trace_id", None)
                if trace_id is not None:
                    if trace_id in seen:
                        continue
                    seen.add(trace_id)
                new_items += 1
                yield item
            page_token = getattr(page, "token", None)
            if len(items) < page_size or not page_token or new_items == 0:
                return
