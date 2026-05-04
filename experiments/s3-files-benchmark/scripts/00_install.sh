#!/bin/bash
# 00_install.sh — install benchmark tooling on AL2023 ARM (Graviton).
# Idempotent. Safe to re-run.
set -euxo pipefail

LOGFILE=/var/log/s3files-bench-install.log
exec > >(tee -a "$LOGFILE") 2>&1
echo "[00_install] start $(date -u +%FT%TZ)"

dnf -y update
dnf -y install fio sysstat jq amazon-efs-utils unzip util-linux-core

# Mountpoint for S3 (mount-s3) — official RPM for AL2023 aarch64
if ! command -v mount-s3 >/dev/null 2>&1; then
  curl -fsSLo /tmp/mount-s3.rpm \
    https://s3.amazonaws.com/mountpoint-s3-release/latest/arm64/mount-s3.rpm
  dnf -y install /tmp/mount-s3.rpm
fi

# Sanity
fio --version
mount-s3 --version
echo "amazon-efs-utils: $(rpm -q amazon-efs-utils)"

echo "[00_install] done $(date -u +%FT%TZ)"
