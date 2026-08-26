# act: docker mounts resolve against the host filesystem

Date first observed: 2026-08-26

## Symptom

`shlepa smoke` (and anything that runs docker through the host daemon)
fails under local `act` with `task: FAIL (unsolved: verifier wrote no
reward.txt (rc=0))` even though the agent actually solved the task —
the reward written by the container lands in an auto-created host
directory, not in the workspace the engine reads.

## Cause

act runs the workflow steps inside a container while the `docker` CLI
talks to the **host** docker daemon. The daemon resolves `-v <path>`
mount sources and `docker cp` destinations on the **host** filesystem.
When the CLI's workspace lives inside the act container's filesystem,
the daemon silently creates empty host-side directories instead, so
the container writes `reward.txt` somewhere the engine never reads.

On real GitHub runners the CLI runs directly on the host, so the paths
are consistent and the problem cannot occur.

## Impact

Local `act` runs of `pr-checks` (smoke step) and `main-full`
(submit-test step) cannot fully validate the docker-dependent stages.
Everything else — uv install, zip build + size/run.sh assertions,
flake8, doctor, container build/run, agent execution, verifier, MLflow
logging — is verifiable under act (and was: reward.txt=1 was found in
the host-side directory for both observed runs).

## Workaround / verification

- Validate the non-docker steps with act:
  `act pull_request -P ubuntu-latest=catthehacker/ubuntu:act-latest --secret-file <file>`
- Validate the docker stages locally on the host: `shlepa smoke` and
  `shlepa submit-test contest-hello-file` (both green as of this writing).
- The final authority is the real GitHub Actions run (see
  docs/runbook.md, CI section).
