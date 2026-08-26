"""Entry-point test: ./run.sh "<instruction>" (the submission contract)."""

import os
import subprocess
from pathlib import Path

from stub_server import FINAL_ANSWER, start_stub_server

REPO_AGENT_DIR = Path(__file__).resolve().parent.parent
VENV_BIN = REPO_AGENT_DIR / ".venv" / "bin"


def test_run_sh_entrypoint(tmp_path):
    server, stub_url = start_stub_server()
    try:
        # The agent runs in an environment that already has the dependencies:
        # the uv venv in dev, the secureintelligent/acp image in the contest.
        env = {
            "PATH": f"{VENV_BIN}:{os.environ['PATH']}",
            "OPENAI_BASE_URL": stub_url,
            "OPENAI_API_KEY": "sk-test",
            "LOCAL_AGENT_MODEL": "stub-model",
            "LOCAL_AGENT_WORKDIR": str(tmp_path),
        }
        run_sh = REPO_AGENT_DIR / "run.sh"
        proc = subprocess.run(
            ["sh", str(run_sh), "Create hello.txt with the exact content hello"],
            capture_output=True,
            text=True,
            env=env,
            cwd=tmp_path,
            timeout=60,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        assert FINAL_ANSWER in proc.stdout
    finally:
        server.shutdown()
        server.server_close()
