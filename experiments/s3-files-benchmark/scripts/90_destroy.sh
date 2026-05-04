#!/bin/bash
# 90_destroy.sh — local cleanup on the EC2 client.
# Unmounts filesystems. Stack/AWS resource destroy is `make destroy`.
set -uxo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/common.sh" 2>/dev/null || true

for mnt in "${MOUNT_S3FILES:-/mnt/s3files}" \
           "${MOUNT_MOUNTPOINT:-/mnt/mountpoint}" \
           "${MOUNT_EFS:-/mnt/efs}"; do
  if mountpoint -q "$mnt"; then
    echo "[90_destroy] umount $mnt"
    fusermount -u "$mnt" 2>/dev/null || umount -f "$mnt" || true
  fi
done

echo "[90_destroy] done"
