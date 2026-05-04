#!/bin/bash
# 45_save_checkpoint.sh — Spot interruption guard.
# Background daemon: polls IMDS for spot interruption notice every 5s.
# On notice (~2 min before forced termination), syncs results dir then exits.
#
# Usage: nohup bash 45_save_checkpoint.sh & disown
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/common.sh"

LOGFILE=/var/log/s3files-bench-spot-watch.log
exec > >(tee -a "$LOGFILE") 2>&1
echo "[45_save_checkpoint] start $(date -u +%FT%TZ) pid=$$"

get_token() {
  curl -fsS -X PUT --max-time 5 \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 3600" \
    http://169.254.169.254/latest/api/token
}

flush_results() {
  echo "[45_save_checkpoint] flushing $RESULT_DIR (already on EFS)"
  sync
  date -u +%FT%TZ > "$RESULT_DIR/.spot_interrupt_marker"
}

TOKEN=$(get_token)
TOKEN_REFRESHED_AT=$(date +%s)

while true; do
  now=$(date +%s)
  if (( now - TOKEN_REFRESHED_AT > 3000 )); then
    TOKEN=$(get_token)
    TOKEN_REFRESHED_AT=$now
  fi

  http_code=$(curl -s -o /tmp/spot_notice -w '%{http_code}' --max-time 5 \
    -H "X-aws-ec2-metadata-token: $TOKEN" \
    http://169.254.169.254/latest/meta-data/spot/instance-action || echo 000)

  if [[ "$http_code" == "200" ]]; then
    echo "[45_save_checkpoint] spot interruption: $(cat /tmp/spot_notice)"
    flush_results
    exit 0
  fi

  sleep 5
done
