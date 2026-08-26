"""Smoke test: the package imports and exposes a version."""

import shlepa_agent


def test_import_and_version():
    assert shlepa_agent.__version__ == "0.1.0"
