"""MLflow tracking client helper.

The remote server uses HTTP basic auth: MLFLOW_TRACKING_USERNAME and
MLFLOW_TRACKING_PASSWORD are folded into the tracking URI's netloc.
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
from urllib.parse import quote, urlsplit, urlunsplit

from mlflow import MlflowClient

from shlepa_cli.config import Settings

_MASK_RE = re.compile(r"(://[^/@\s]+:)([^@\s]+)@")


def mask_url_auth(url: str) -> str:
    """Mask the basic-auth password in a URL for display purposes.

    ``https://user:secret@host/x`` -> ``https://user:***@host/x``. URLs
    without userinfo are returned unchanged.
    """
    return _MASK_RE.sub(r"\1***@", url)


@contextlib.contextmanager
def masked_client_stdout():
    """Re-emit whatever sys.stdout receives, with credentials masked.

    The MLflow client prints View-run URLs straight to stdout and the
    URL it computes carries the tracking URI's embedded basic-auth
    credentials (the 3.x client has no username/password parameters).
    Wrap MlflowClient calls that print (create_run & co) with this.
    """
    real = sys.stdout
    buffer = io.StringIO()
    sys.stdout = buffer
    try:
        yield
    finally:
        sys.stdout = real
        leaked = buffer.getvalue()
        if leaked:
            real.write(mask_url_auth(leaked))
            real.flush()


def build_tracking_uri(
    base_uri: str, username: str | None, password: str | None
) -> str:
    """Return ``base_uri`` with basic-auth credentials in the netloc.

    No credentials -> the URI is returned unchanged. Existing userinfo
    in the URI is replaced.
    """
    parts = urlsplit(base_uri)
    if username and password:
        netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{parts.hostname}"
        if parts.port is not None:
            netloc += f":{parts.port}"
    else:
        netloc = parts.netloc
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def get_mlflow_client(settings: Settings) -> MlflowClient:
    """Build an authenticated MlflowClient from settings.

    Raises ValueError when MLFLOW_TRACKING_URI is not configured.
    """
    if not settings.mlflow_tracking_uri:
        raise ValueError(
            "MLFLOW_TRACKING_URI is not set (see .env.example)"
        )
    uri = build_tracking_uri(
        settings.mlflow_tracking_uri,
        settings.mlflow_tracking_username,
        settings.mlflow_tracking_password,
    )
    return MlflowClient(tracking_uri=uri)
