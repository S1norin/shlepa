"""Tests for the subprocess-backed DockerClient command lines."""

import subprocess
from pathlib import Path

from shlepa_cli.docker_client import DockerClient, Mount


def test_run_supports_network_host(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="cid123\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    client = DockerClient()
    client.run(
        "shlepa-x-1",
        "shlepa-task-x:dev",
        [Mount(Path("/tmp/ws/logs/verifier"), "/logs/verifier")],
        {},
        network="host",
    )
    assert calls[0] == [
        "docker",
        "run",
        "-d",
        "--name",
        "shlepa-x-1",
        "--network",
        "host",
        "-v",
        "/tmp/ws/logs/verifier:/logs/verifier",
        "shlepa-task-x:dev",
        "sleep",
        "infinity",
    ]


def test_run_without_network_omits_flag(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="cid123\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    DockerClient().run("n", "img", [], {})
    assert "--network" not in calls[0]


def test_exec_accepts_timeout(monkeypatch):
    calls: list[list[str]] = []
    timeouts: list = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "timeout" in kwargs:
            timeouts.append(kwargs["timeout"])
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    client = DockerClient()
    client.exec("c1", ["bash", "/tests/test.sh"], {}, timeout=42)
    assert calls[0] == ["docker", "exec", "c1", "bash", "/tests/test.sh"]
    assert timeouts == [42]
    # No timeout given -> the default (900s) is used.
    client.exec("c1", ["ls"], {})
    assert timeouts[-1] == 900


def test_cp_out(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    DockerClient().cp_out("c1", "/app", Path("/tmp/ws/app"))
    assert calls[0] == ["docker", "cp", "c1:/app", "/tmp/ws/app"]


def test_cp_out_failure_raises(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no such path")

    monkeypatch.setattr("subprocess.run", fake_run)
    try:
        DockerClient().cp_out("c1", "/app", Path("/tmp/ws/app"))
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "no such path" in str(exc)
