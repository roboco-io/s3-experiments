#!/bin/bash
# 50_run_all.sh — orchestrate the 36-cell sweep.
# 3 runs × 3 systems × 4 profiles. Resumable via checkpoint.json.
# Starts 45_save_checkpoint.sh in background as Spot interruption guard.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/common.sh"

LOGFILE=/var/log/s3files-bench-run-all.log
exec > >(tee -a "$LOGFILE") 2>&1
echo "[50_run_all] start $(date -u +%FT%TZ)"

# Spot guard daemon
nohup bash "$SCRIPT_DIR/45_save_checkpoint.sh" >/dev/null 2>&1 &
SPOT_PID=$!
trap 'kill $SPOT_PID 2>/dev/null || true' EXIT

CKPT="$RESULT_DIR/checkpoint.json"
[[ -f "$CKPT" ]] || echo '{"done":[]}' > "$CKPT"

is_done() {
  python3 - "$CKPT" "$1" "$2" "$3" <<'PY'
import json, sys
ckpt, run, sys_, prof = sys.argv[1:]
with open(ckpt) as f:
    data = json.load(f)
for d in data.get("done", []):
    if d == {"run": int(run), "system": sys_, "profile": prof}:
        sys.exit(0)
sys.exit(1)
PY
}

RUNS=(1 2 3)
TOTAL=$(( ${#RUNS[@]} * ${#systems_all[@]} * ${#profiles_all[@]} ))
DONE=0

for run in "${RUNS[@]}"; do
  for sys in "${systems_all[@]}"; do
    for p in "${profiles_all[@]}"; do
      DONE=$((DONE+1))
      if is_done "$run" "$sys" "$p"; then
        echo "[50_run_all] skip ($DONE/$TOTAL) run=$run sys=$sys profile=$p (already done)"
        continue
      fi
      echo "[50_run_all] run ($DONE/$TOTAL) run=$run sys=$sys profile=$p"
      if ! "$SCRIPT_DIR/40_run_one.sh" "$run" "$sys" "$p"; then
        echo "[50_run_all] cell failed run=$run sys=$sys profile=$p (continuing)"
      fi
    done
  done
done

echo "[50_run_all] all 36 cells attempted $(date -u +%FT%TZ)"
date -u +%FT%TZ > "$RESULT_DIR/.run_all_done"

# Per spec: instance auto-shutdown after completion (terminate via market option)
if [[ "${SHUTDOWN_ON_DONE:-1}" == "1" ]]; then
  echo "[50_run_all] requesting shutdown -h now"
  shutdown -h +1 "s3-files-benchmark complete"
fi
