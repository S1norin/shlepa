#!/usr/bin/env bash
# Sequential A/B sweep of toolset arms for one experiment preset.
#
# Usage:
#   scripts/ab-sweep.sh [preset] [arm ...]
#
#   preset   experiment preset name (default: all)
#   arms     arm names (default: baseline +smart-grep +sifs);
#            see agent/shlepa_agent/toolsets.py for the full set
#
# Each arm runs as its own `shlepa run` invocation (its own batch id).
# Arms run sequentially; a failed arm is recorded and the sweep continues.
#
# Output (tmp/ is gitignored, cleaned by `shlepa clean` after 7 days):
#   tmp/ab-sweep/<ts>-<preset>/sweep.jsonl  one line per arm:
#     preset, arm, git_sha, batch_id, exit code, log path
#   tmp/ab-sweep/<ts>-<preset>/<arm>.log    full `shlepa run` output per arm
#
# Suggested launch (survives terminal close; tail the log to watch):
#   tmux new -d -s ab-sweep "scripts/ab-sweep.sh all 2>&1 | tee tmp/ab-sweep/launch.log"
#   tmux attach -t ab-sweep
#
# Compare results afterwards:
#   - MLflow: filter runs in the family experiment by the `toolset` tag
#   - digests: uv run --project cli --no-sync shlepa trace-export --batch <batch_id>
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRESET="${1:-all}"
shift || true
if [ "$#" -gt 0 ]; then
  ARMS=("$@")
else
  ARMS=(baseline +smart-grep +sifs)
fi

SHLEPA=(uv run --project cli --no-sync shlepa)
TS="$(date -u +%Y%m%d-%H%M%S)"
OUT="$ROOT/tmp/ab-sweep/$TS-$PRESET"
mkdir -p "$OUT"

echo "ab-sweep: preset=$PRESET arms=${ARMS[*]}"
echo "ab-sweep: out=$OUT"

# One sweep at a time.
exec 9>"$ROOT/tmp/ab-sweep/.lock"
if ! flock -n 9; then
  echo "ab-sweep: another sweep is running (lock held), aborting" >&2
  exit 2
fi

# Sanity: endpoint/MLflow/docker must be healthy before spending hours.
echo "== doctor --probe =="
if ! "${SHLEPA[@]}" doctor --probe; then
  echo "ab-sweep: doctor failed, aborting" >&2
  exit 2
fi

# Validate preset + arms up front (cheap dry runs catch typos early).
for arm in "${ARMS[@]}"; do
  echo "== dry-run: preset=$PRESET arm=$arm =="
  if ! "${SHLEPA[@]}" run "$PRESET" --arm "$arm" --dry-run; then
    echo "ab-sweep: preset/arm validation failed for $PRESET / $arm, aborting" >&2
    exit 2
  fi
done

GIT_SHA="$(git -C "$ROOT" rev-parse --short HEAD)"
FAILED=0
: > "$OUT/sweep.jsonl"

for arm in "${ARMS[@]}"; do
  log="$OUT/$arm.log"
  echo ""
  echo "== arm: $arm (log: $log) =="
  "${SHLEPA[@]}" run "$PRESET" --arm "$arm" >"$log" 2>&1
  rc=$?
  batch_id="$(grep -m1 -oE 'batch: [0-9]{8}-[0-9]{6}-[0-9a-f]{6}' "$log" | awk '{print $2}')"
  [ -n "$batch_id" ] || batch_id="?"
  echo "   arm=$arm exit=$rc batch=$batch_id"
  printf '{"preset":"%s","arm":"%s","git_sha":"%s","batch_id":"%s","exit":%d,"log":"%s"}\n' \
    "$PRESET" "$arm" "$GIT_SHA" "$batch_id" "$rc" "${log#"$ROOT"/}" >> "$OUT/sweep.jsonl"
  [ "$rc" -eq 0 ] || FAILED=1
done

echo ""
echo "== sweep done (failed arms: $FAILED) =="
cat "$OUT/sweep.jsonl"
echo ""
echo "Compare in MLflow by the `toolset` tag; per-task digests via:"
echo "  uv run --project cli --no-sync shlepa trace-export --batch <batch_id>   (per arm, from sweep.jsonl)"
[ "$FAILED" -eq 0 ] || exit 1
