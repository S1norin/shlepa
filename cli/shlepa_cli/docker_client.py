"""Thin docker wrapper for task environment containers.

The engine depends on the :class:`DockerLike` protocol so tests can
inject a fake; :class:`DockerClient` is the subprocess-backed
implementation.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Mount:
    """A bind mount: host path -> container path (read-only flag)."""

    host: Path
    target: str
    readonly: bool = False


class DockerLike(Protocol):
    """Docker operations the run engine needs."""

    def build(self, image: str, context: Path) -> None:
        """Build an image from a Dockerfile context."""
        ...

    def run(self, name: str, image: str, mounts: list[Mount], env: dict[str, str]) -> str:
        """Start a detached container; returns the container id."""
        ...

    def exec(
        self, name: str, cmd: list[str], env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        """Run a command inside the container."""
        ...

    def stop(self, name: str) -> None:
        """Stop (and remove) the container."""
        ...


class DockerClient:
    """subprocess-backed DockerLike."""

    def build(self, image: str, context: Path) -> None:
        proc = subprocess.run(
            ["docker", "build", "-t", image, str(context)],
            capture_output=True,
            text=True,
            timeout=3600,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"docker build failed for {image}:\n{proc.stderr[-2000:]}"
            )

    def run(self, name: str, image: str, mounts: list[Mount], env: dict[str, str]) -> str:
        cmd = ["docker", "run", "-d", "--name", name]
        for mount in mounts:
            spec = f"{mount.host}:{mount.target}"
            if mount.readonly:
                spec += ":ro"
            cmd += ["-v", spec]
        for key, value in env.items():
            cmd += ["-e", f"{key}={value}"]
        cmd += [image, "sleep", "infinity"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(
                f"docker run failed for {name}:\n{proc.stderr[-2000:]}"
            )
        return proc.stdout.strip()

    def exec(
        self, name: str, cmd: list[str], env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        docker_cmd = ["docker", "exec"]
        for key, value in env.items():
            docker_cmd += ["-e", f"{key}={value}"]
        return subprocess.run(
            [*docker_cmd, name, *cmd], capture_output=True, text=True, timeout=900
        )

    def stop(self, name: str) -> None:
        subprocess.run(
            ["docker", "stop", "-t", "10", name],
            capture_output=True,
            text=True,
            timeout=120,
        )
