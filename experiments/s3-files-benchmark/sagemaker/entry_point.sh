#!/bin/bash
# SageMaker training-job entry point.
# Installs minimum tooling, then runs the mount-attempt PoC.
set -uxo pipefail

# yum is available on AWS DLC; dnf on AL2023-based images
if command -v dnf >/dev/null 2>&1; then PKG=dnf; else PKG=yum; fi

$PKG -y install amazon-efs-utils awscli || true

# mount-s3 for AL2023 aarch64 / amd64
ARCH=$(uname -m)
case "$ARCH" in
  aarch64) MS3_ARCH=arm64 ;;
  x86_64)  MS3_ARCH=x86_64 ;;
  *) echo "unknown arch $ARCH"; MS3_ARCH=x86_64 ;;
esac
if ! command -v mount-s3 >/dev/null 2>&1; then
  curl -fsSLo /tmp/mount-s3.rpm \
    "https://s3.amazonaws.com/mountpoint-s3-release/latest/${MS3_ARCH}/mount-s3.rpm" || true
  $PKG -y install /tmp/mount-s3.rpm || true
fi

python3 /opt/ml/code/train.py
