#!/bin/bash
# 40_run_one.sh <run> <system> <profile>
# Runs one (run, system, profile) cell. Auto-falls-back to direct=0 if O_DIRECT
# is rejected (NFSv4/FUSE may not support it).
set -euxo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/common.sh"

RUN="${1:?run number, e.g. 1}"
SYS="${2:?system: s3files|mountpoint|efs}"
PROFILE="${3:?profile: p1_shard_seq_read|p2_random_read_4k|p3_checkpoint_write|p4_mixed_train}"

FIO_PROFILE_DIR="${SCRIPT_DIR}/../fio"
PROFILE_FILE="${FIO_PROFILE_DIR}/${PROFILE}.fio"
[[ -f "$PROFILE_FILE" ]] || { echo "missing $PROFILE_FILE" >&2; exit 2; }

mnt="$(mount_dir_for "$SYS")"
# P3 writes new files at run time → use a per-run dir to keep results clean
case "$PROFILE" in
  p3_checkpoint_write)
    FIO_DIR="$mnt/_run/run${RUN}/${PROFILE}"
    mkdir -p "$FIO_DIR"
    ;;
  *)
    FIO_DIR="$mnt/_seed/${PROFILE}"
    ;;
esac

OUT_RAW="$RESULT_DIR/raw"
mkdir -p "$OUT_RAW"
OUT_JSON="$OUT_RAW/${RUN}_${SYS}_${PROFILE}.json"
OUT_CPU="$OUT_RAW/${RUN}_${SYS}_${PROFILE}_cpu.txt"
OUT_LOG="$OUT_RAW/${RUN}_${SYS}_${PROFILE}.log"

# Force cold cache for this system
"$SCRIPT_DIR/30_cold_setup.sh" "$SYS" 2>&1 | tee -a "$OUT_LOG"

run_fio() {
  local direct="$1"
  FIO_DIR="$FIO_DIR" FIO_DIRECT="$direct" \
    fio --output-format=json+ --output="$OUT_JSON" "$PROFILE_FILE"
}

# CPU sampler in background
mpstat 1 60 > "$OUT_CPU" &
MPSTAT_PID=$!

# Try direct=1 first; on EINVAL retry direct=0 + drop_caches
if ! run_fio 1 2>>"$OUT_LOG"; then
  echo "[40_run_one] direct=1 failed for $SYS/$PROFILE; retrying direct=0" | tee -a "$OUT_LOG"
  sync; echo 3 > /proc/sys/vm/drop_caches
  run_fio 0 2>>"$OUT_LOG"
  echo "{\"fallback_direct\": 0}" > "$OUT_RAW/${RUN}_${SYS}_${PROFILE}.fallback.json"
fi

wait "$MPSTAT_PID" || true

# Update checkpoint
CKPT="$RESULT_DIR/checkpoint.json"
python3 - "$CKPT" "$RUN" "$SYS" "$PROFILE" <<'PY'
import json, sys, os
ckpt_path, run, sys_, prof = sys.argv[1:]
data = {}
if os.path.exists(ckpt_path):
    with open(ckpt_path) as f:
        data = json.load(f)
data.setdefault("done", []).append({"run": int(run), "system": sys_, "profile": prof})
with open(ckpt_path, "w") as f:
    json.dump(data, f, indent=2)
PY

echo "[40_run_one] done $RUN $SYS $PROFILE -> $OUT_JSON"
