#!/bin/bash
# 30_cold_setup.sh <system> — force cold cache for the named system.
# 1. drop kernel page/dentry/inode caches
# 2. umount + remount the system's filesystem (kills NFS/FUSE client caches)
#
# NOTE: Seed files at $MOUNT/_seed/$profile/ are reused across runs;
# uniqueness within a fio run is fio's default. Across runs, cache
# invalidation here is the cold guarantee. See spec R3/R4 limitations.
set -euxo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/common.sh"

sys="${1:?usage: 30_cold_setup.sh <s3files|mountpoint|efs>}"
mnt="$(mount_dir_for "$sys")"

# 1) Kernel caches
sync
echo 3 > /proc/sys/vm/drop_caches

# 2) Umount + remount the specific filesystem
case "$sys" in
  efs)
    umount -f "$mnt" || true
    mount -t efs -o tls,iam "$EFS_FS_ID":/ "$mnt"
    ;;
  s3files)
    umount -f "$mnt" || true
    mount -t s3files "$S3FILES_FS_ID":/ "$mnt"
    ;;
  mountpoint)
    fusermount -u "$mnt" 2>/dev/null || umount -f "$mnt" || true
    mount-s3 "$BUCKET_B" "$mnt" --allow-other --region "$AWS_REGION"
    ;;
esac

# Sanity: directory should be readable post-remount
if ! ls "$mnt" >/dev/null 2>&1; then
  echo "[30_cold_setup] $mnt not readable after remount" >&2
  exit 1
fi
