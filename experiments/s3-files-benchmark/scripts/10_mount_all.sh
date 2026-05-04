#!/bin/bash
# 10_mount_all.sh — mount the three filesystems.
# Idempotent (skips if already mounted).
set -euxo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/common.sh"

LOGFILE=/var/log/s3files-bench-mount.log
exec > >(tee -a "$LOGFILE") 2>&1
echo "[10_mount_all] start $(date -u +%FT%TZ)"

mkdir -p "$MOUNT_S3FILES" "$MOUNT_MOUNTPOINT" "$MOUNT_EFS"

mount_or_skip() {
  local target="$1"; shift
  if mountpoint -q "$target"; then
    echo "[10_mount_all] $target already mounted, skipping"
    return
  fi
  "$@"
}

# EFS (TLS to mount target via amazon-efs-utils)
mount_or_skip "$MOUNT_EFS" \
  mount -t efs -o tls "$EFS_FS_ID":/ "$MOUNT_EFS"

# S3 Files (NFSv4.1+ via amazon-efs-utils 's3files' type)
mount_or_skip "$MOUNT_S3FILES" \
  mount -t s3files "$S3FILES_FS_ID":/ "$MOUNT_S3FILES"

# Mountpoint for S3 (FUSE), explicit --no-cache for fairness
mount_or_skip "$MOUNT_MOUNTPOINT" \
  mount-s3 "$BUCKET_B" "$MOUNT_MOUNTPOINT" \
    --no-cache --allow-other --region "$AWS_REGION"

mount | grep -E "$MOUNT_S3FILES|$MOUNT_MOUNTPOINT|$MOUNT_EFS"
echo "[10_mount_all] done $(date -u +%FT%TZ)"
