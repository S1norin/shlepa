"""Tests for deterministic submission-contract validation."""

import zipfile

from shlepa_cli.compliance import check_submission, passed


def _make_submission(path, *, run_sh=None, extra=None):
    script = run_sh or (
        "#!/bin/sh\n"
        "exec python3 -m app \"$@\"\n"
    )
    app = (
        "import os\n"
        "MODEL = os.environ['LOCAL_AGENT_MODEL']\n"
        "URL = os.environ['OPENAI_BASE_URL']\n"
        "KEY = os.environ['OPENAI_API_KEY']\n"
    )
    with zipfile.ZipFile(path, "w") as zf:
        info = zipfile.ZipInfo("run.sh")
        info.external_attr = (0o755 << 16) | 0x8000
        zf.writestr(info, script)
        zf.writestr("app.py", app)
        for name, source in (extra or {}).items():
            zf.writestr(name, source)
    return path


def _by_name(checks):
    return {check.name: check for check in checks}


def test_valid_submission_passes(tmp_path):
    checks = check_submission(_make_submission(tmp_path / "submission.zip"))
    assert passed(checks)


def test_submission_rejects_runtime_install_and_development_files(tmp_path):
    checks = check_submission(
        _make_submission(
            tmp_path / "submission.zip",
            run_sh="#!/bin/sh\npip install extras\n",
            extra={"telemetry/trace.py": "import mlflow\n"},
        )
    )
    by_name = _by_name(checks)
    assert not by_name["no_runtime_installs"].ok
    assert not by_name["development_files_excluded"].ok
    assert not by_name["no_dev_dependencies"].ok


def test_submission_requires_root_entrypoint_and_endpoint_contract(tmp_path):
    path = tmp_path / "submission.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("bin/run.sh", "#!/bin/sh\n")
    by_name = _by_name(check_submission(path))
    assert not by_name["entrypoint"].ok
    assert not by_name["endpoint_contract"].ok
