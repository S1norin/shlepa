#!/usr/bin/env bash
# taskctl.sh — container control for manual solution sessions.
# Usage:
#   taskctl.sh up <slug>      start (or restart) the task container
#   taskctl.sh verify <slug>  run tests/test.sh, print reward, copy /app out
#   taskctl.sh out <slug>     copy container /app to workspace
#   taskctl.sh down <slug>    stop + remove the container (image kept)
set -euo pipefail

REPO="/home/andreipc/shlepa"
CMD="${1:?usage: taskctl.sh <up|verify|out|down> <slug>}"
SLUG="${2:?usage: taskctl.sh <up|verify|out|down> <slug>}"
NAME="shlepa-manual-${SLUG}"
WS="${REPO}/tmp/manual-${SLUG}"
TASK="${REPO}/tasks/${SLUG}"
IMAGE="shlepa-task-${SLUG}:env"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -d "$TASK" ]] || die "task dir not found: $TASK"
mkdir -p "$WS/logs/verifier"

up() {
  if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "building $IMAGE (image missing)"
    docker build -t "$IMAGE" "$TASK/environment"
  fi
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -f "$WS/logs/verifier/reward.txt"
  docker run -d --name "$NAME" --network host \
    -v "${TASK}/tests:/tests:ro" \
    -v "${WS}/logs/verifier:/logs/verifier" \
    "$IMAGE" sleep infinity >/dev/null
  sleep 3
  local st
  st="$(docker inspect -f '{{.State.Status}}' "$NAME" 2>/dev/null || true)"
  [[ "$st" == "running" ]] || die "container $NAME not running (state=$st)"
  echo "container $NAME up (image $IMAGE)"
}

verify() {
  local st
  st="$(docker inspect -f '{{.State.Status}}' "$NAME" 2>/dev/null || true)"
  [[ "$st" == "running" ]] || die "container $NAME not running (state=$st); run: taskctl.sh up $SLUG"
  rm -f "$WS/logs/verifier/reward.txt"
  local rc=0
  timeout 300 docker exec "$NAME" bash /tests/test.sh >/dev/null 2>&1 || rc=$?
  if [[ -f "$WS/logs/verifier/reward.txt" ]]; then
    local reward
    reward="$(tr -d '[:space:]' < "$WS/logs/verifier/reward.txt")"
    echo "reward=${reward:-EMPTY} (test.sh rc=$rc)"
  else
    echo "reward=MISSING (test.sh rc=$rc)"
    [[ -f "$WS/logs/verifier/verifier.log" ]] && tail -5 "$WS/logs/verifier/verifier.log"
  fi
}

out() {
  rm -rf "$WS/app"
  docker cp "$NAME:/app" "$WS/app"
  echo "copied /app -> $WS/app"
}

down() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  echo "container $NAME removed"
}

case "$CMD" in
  up) up ;;
  verify) verify ;;
  out) out ;;
  down) down ;;
  *) die "unknown command: $CMD" ;;
esac
