#!/bin/bash
# collect_results.sh — pull raw fio JSON + mpstat from EFS to local output/.
# Run from the local workstation (after EC2 finishes, before make destroy).
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
LOCAL_OUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/output"
mkdir -p "$LOCAL_OUT/raw"

INSTANCE_ID=$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:Project,Values=s3-files-benchmark" \
            "Name=instance-state-name,Values=running,stopping,stopped" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)

if [[ -z "$INSTANCE_ID" || "$INSTANCE_ID" == "None" ]]; then
  echo "[collect] no running benchmark instance found in $REGION" >&2
  exit 1
fi
echo "[collect] using $INSTANCE_ID"

# Run via SSM: tar the EFS results dir, base64-encode, return inline
CMD_ID=$(aws ssm send-command --region "$REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters commands='["set -e; tar czf /tmp/results.tar.gz -C /mnt/efs results || tar czf /tmp/results.tar.gz -C / mnt/efs/results; base64 /tmp/results.tar.gz"]' \
  --query 'Command.CommandId' --output text)

echo "[collect] SSM command $CMD_ID — waiting"
aws ssm wait command-executed --region "$REGION" \
  --command-id "$CMD_ID" --instance-id "$INSTANCE_ID"

aws ssm get-command-invocation --region "$REGION" \
  --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" \
  --query StandardOutputContent --output text \
  | base64 -d > "$LOCAL_OUT/results.tar.gz"

tar xzf "$LOCAL_OUT/results.tar.gz" -C "$LOCAL_OUT" --strip-components=1
rm "$LOCAL_OUT/results.tar.gz"
echo "[collect] extracted to $LOCAL_OUT"
ls -la "$LOCAL_OUT/raw" | head -20
