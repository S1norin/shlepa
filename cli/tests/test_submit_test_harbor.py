"""Tests for submit_test: submission unzip + Harbor command construction."""

import os
import stat
import zipfile

from shlepa_cli import submit_test


def _make_zip(path):
    """Create a flat-layout submission zip (like zip_build produces)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("run.sh")
        info.external_attr = (0o755 << 16) | 0x8000
        zf.writestr(info, "#!/bin/sh\necho hi\n")
        zf.writestr("agent.py", "class MyInstalledAgent: pass\n")
        zf.writestr("shlepa_agent/__init__.py", "__version__ = '1'\n")
        zf.writestr("shlepa_agent/core.py", "x = 1\n")
    return path


def test_unzip_flat_layout_and_exec_bit(tmp_path):
    zip_path = _make_zip(tmp_path / "sub.zip")
    dest = tmp_path / "unzipped"
    out = submit_test.unzip_submission(zip_path, dest)
    assert out == dest
    assert (dest / "run.sh").is_file()
    assert (dest / "agent.py").is_file()
    assert (dest / "shlepa_agent" / "__init__.py").is_file()
    mode = os.stat(dest / "run.sh").st_mode
    assert mode & stat.S_IXUSR and mode & stat.S_IXGRP and mode & stat.S_IXOTH


def test_unzip_rejects_path_traversal(tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../evil.txt", "pwned")
        zf.writestr("agent.py", "class MyInstalledAgent: pass\n")
    try:
        submit_test.unzip_submission(evil, tmp_path / "out")
        raise AssertionError("expected UnzipError")
    except submit_test.UnzipError:
        pass
    assert not (tmp_path / "evil.txt").exists()


def test_unzip_requires_agent_py(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("run.sh", "#!/bin/sh\n")
    try:
        submit_test.unzip_submission(bad, tmp_path / "out")
        raise AssertionError("expected UnzipError")
    except submit_test.UnzipError:
        pass


def test_build_harbor_command_basic(tmp_path):
    argv, env = submit_test.build_harbor_command(
        agent_dir=tmp_path / "agent",
        task_path=tmp_path / "tasks" / "contest-hello-file",
        model="model-x",
        jobs_dir=tmp_path / "jobs",
        job_name="job-1",
        harbor_exe_path=tmp_path / "harbor",
    )
    assert argv[0] == str(tmp_path / "harbor")
    assert argv[1:3] == ["job", "start"]
    assert "--agent" in argv
    assert argv[argv.index("--agent") + 1] == "agent:MyInstalledAgent"
    assert argv[argv.index("-m") + 1] == "model-x"
    assert argv[argv.index("--env") + 1] == "docker"
    assert argv[argv.index("--path") + 1] == str(tmp_path / "tasks" / "contest-hello-file")
    assert argv[argv.index("--jobs-dir") + 1] == str(tmp_path / "jobs")
    assert argv[argv.index("--job-name") + 1] == "job-1"
    assert argv[argv.index("--n-concurrent") + 1] == "1"
    assert "--yes" in argv
    assert "--ae" not in argv  # no endpoint creds passed
    assert env["PYTHONPATH"] == str(tmp_path / "agent")


def test_build_harbor_command_with_endpoint(tmp_path):
    argv, env = submit_test.build_harbor_command(
        agent_dir=tmp_path / "agent",
        task_path=tmp_path / "t",
        model="model-x",
        jobs_dir=tmp_path / "jobs",
        job_name="job-2",
        base_url="http://100.98.79.56:9999/v1",
        api_key="sekret",
        harbor_exe_path=tmp_path / "harbor",
    )
    assert "--ae" in argv
    ae = [argv[i + 1] for i in range(len(argv) - 1) if argv[i] == "--ae"]
    assert "OPENAI_BASE_URL=http://100.98.79.56:9999/v1" in ae
    assert "OPENAI_API_KEY=sekret" in ae


def test_build_harbor_command_preprends_existing_pythonpath(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/existing")
    argv, env = submit_test.build_harbor_command(
        agent_dir=tmp_path / "agent",
        task_path=tmp_path / "t",
        model="model-x",
        jobs_dir=tmp_path / "jobs",
        job_name="job-3",
        harbor_exe_path=tmp_path / "harbor",
    )
    paths = env["PYTHONPATH"].split(os.pathsep)
    assert paths[0] == str(tmp_path / "agent")
    assert "/existing" in paths


def test_harbor_exe_defaults_to_venv_script(tmp_path):
    argv, _ = submit_test.build_harbor_command(
        agent_dir=tmp_path / "agent",
        task_path=tmp_path / "t",
        model="model-x",
        jobs_dir=tmp_path / "jobs",
        job_name="job-4",
    )
    assert argv[0].endswith("harbor")
