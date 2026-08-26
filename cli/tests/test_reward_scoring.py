"""Tests for the contest-faithful container verifier (test.sh -> reward.txt)."""

import subprocess
from pathlib import Path

from shlepa_cli import run_engine
from shlepa_cli.tasks import Task


def _task(root: Path, with_test_sh=True, verifier_env=None, verifier_timeout=120):
    task_dir = root / "tasks" / "contest-hello-file"
    (task_dir / "tests").mkdir(parents=True)
    if with_test_sh:
        (task_dir / "tests" / "test.sh").write_text("#!/bin/bash\n")
    (task_dir / "instruction.md").write_text("Create hello.txt")
    return Task(
        slug="contest-hello-file",
        name="contest-hello-file",
        path=task_dir,
        timeout_sec=120,
        env={},
        verifier_env=dict(verifier_env or {}),
        verifier_timeout_sec=verifier_timeout,
    )


class FakeDocker:
    """Simulates the container: the test.sh exec 'writes' the reward file
    through the host-mounted /logs/verifier."""

    def __init__(self, reward: str | None = "1", rc=0, out="verifier done"):
        self.reward = reward
        self.rc = rc
        self.out = out
        self.reward_file: Path | None = None
        self.execs: list[tuple[str, list[str], dict, object]] = []

    def exec(self, name, cmd, env, timeout=None):
        self.execs.append((name, list(cmd), dict(env), timeout))
        if cmd[-1] == "/tests/test.sh" and self.reward_file is not None:
            if self.reward is None:
                if self.reward_file.exists():
                    self.reward_file.unlink()
            else:
                self.reward_file.write_text(self.reward)
        return subprocess.CompletedProcess(cmd, self.rc, stdout=self.out, stderr="")


def test_reward_solved(tmp_path: Path):
    reward = tmp_path / "reward.txt"
    fake = FakeDocker(reward="1")
    fake.reward_file = reward
    solved, detail = run_engine._score_container_faithful(
        fake, "container-1", _task(tmp_path), reward
    )
    assert solved is True
    assert "reward=1" in detail


def test_reward_unsolved(tmp_path: Path):
    reward = tmp_path / "reward.txt"
    fake = FakeDocker(reward="0")
    fake.reward_file = reward
    solved, detail = run_engine._score_container_faithful(
        fake, "container-1", _task(tmp_path), reward
    )
    assert solved is False
    assert "reward=0" in detail


def test_verifier_wrote_no_reward(tmp_path: Path):
    reward = tmp_path / "reward.txt"
    fake = FakeDocker(reward=None)
    fake.reward_file = reward
    solved, detail = run_engine._score_container_faithful(
        fake, "container-1", _task(tmp_path), reward
    )
    assert solved is False
    assert "no reward.txt" in detail


def test_no_test_sh(tmp_path: Path):
    reward = tmp_path / "reward.txt"
    fake = FakeDocker()
    solved, detail = run_engine._score_container_faithful(
        fake, "container-1", _task(tmp_path, with_test_sh=False), reward
    )
    assert solved is False
    assert "test.sh" in detail
    assert fake.execs == []


def test_exec_command_env_and_timeout(tmp_path: Path):
    reward = tmp_path / "reward.txt"
    fake = FakeDocker(reward="1")
    fake.reward_file = reward
    task = _task(tmp_path, verifier_env={"FOO": "bar"}, verifier_timeout=99)
    run_engine._score_container_faithful(fake, "c", task, reward)
    name, cmd, env, timeout = fake.execs[0]
    assert name == "c"
    assert cmd == ["bash", "/tests/test.sh"]
    assert env == {"FOO": "bar"}
    assert timeout == 99
