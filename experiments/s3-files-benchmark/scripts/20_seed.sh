#!/bin/bash
# 20_seed.sh — pre-create the file trees fio will read from.
# Uses fio --create_only=1 against each mount point so fio's own layout
# matches what it will read at run time. Pre-creating means the cold-read
# measurement reflects storage-side cold latency (page cache cleared via
# drop_caches + remount in 30_cold_setup.sh), not file-creation cost.
#
# IMPORTANT: per Amendment 1 R4, "S3-cold" with the seed-via-mount path
# means data is in the S3 backing bucket but the underlying EFS-backed
# cache may have it warm. Documented limitation.
set -euxo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/common.sh"

LOGFILE=/var/log/s3files-bench-seed.log
exec > >(tee -a "$LOGFILE") 2>&1
echo "[20_seed] start $(date -u +%FT%TZ)"

FIO_DIR_PROFILES=("${SCRIPT_DIR}/../fio")

seed_one_profile() {
  local sys="$1" profile="$2"
  local mnt; mnt="$(mount_dir_for "$sys")"
  local seed_root="$mnt/_seed/$profile"
  mkdir -p "$seed_root"
  echo "[20_seed] $sys/$profile -> $seed_root"
  FIO_DIR="$seed_root" FIO_DIRECT=0 \
    fio --create_only=1 \
        "${FIO_DIR_PROFILES[0]}/${profile}.fio"
}

for sys in "${systems_all[@]}"; do
  for p in "${profiles_all[@]}"; do
    # P3 (checkpoint-write) writes new files at run time; no pre-seed needed.
    [[ "$p" == "p3_checkpoint_write" ]] && continue
    seed_one_profile "$sys" "$p"
  done
done

# Persist last-seed marker so re-runs can skip if same revision
date -u +%FT%TZ > "$RESULT_DIR/.seed_done"
echo "[20_seed] done $(date -u +%FT%TZ)"
