#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
WORKDIR="${LOCAL_AGENT_WORKDIR:-$(pwd)}"

if [ "$#" -lt 1 ]; then
  echo "Usage: ./run.sh PROMPT"
  exit 1
fi

PROMPT="$*"

exec env LOCAL_AGENT_WORKDIR="$WORKDIR" PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 -m shlepa_agent "$PROMPT"
