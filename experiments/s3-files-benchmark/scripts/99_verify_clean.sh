#!/bin/bash
# 99_verify_clean.sh — grep AWS for any leftover resources tagged
# Project=s3-files-benchmark. Exits 0 if clean, 1 if anything remains.
set -uo pipefail

REGION="${AWS_REGION:-us-east-1}"
TAG_KEY=Project
TAG_VAL=s3-files-benchmark
LEFT=0

note() { echo "[verify] $*"; }
fail() { echo "[verify-LEFTOVER] $*"; LEFT=$((LEFT+1)); }
empty_or_none() { [[ -z "$1" || "$1" == "None" ]]; }

# 1. EC2 instances
note "EC2 instances tagged $TAG_KEY=$TAG_VAL ..."
ids=$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:$TAG_KEY,Values=$TAG_VAL" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[].Instances[].InstanceId' --output text)
empty_or_none "$ids" && note "  (none)" || fail "  EC2: $ids"

# 2. CloudFormation stacks
note "CFN stacks starting with S3FilesBenchmark-..."
stacks=$(aws cloudformation list-stacks --region "$REGION" \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE ROLLBACK_COMPLETE DELETE_FAILED \
  --query "StackSummaries[?starts_with(StackName, 'S3FilesBenchmark-')].StackName" \
  --output text)
empty_or_none "$stacks" && note "  (none)" || fail "  CFN: $stacks"

# 3. S3 buckets
note "S3 buckets s3files-bench-* ..."
buckets=$(aws s3 ls 2>/dev/null | awk '{print $3}' | grep -E '^s3files-bench-' || true)
empty_or_none "$buckets" && note "  (none)" || fail "  S3: $buckets"

# 4. S3 Files filesystems (note: field name is `fileSystems`, lowercase f)
note "S3 Files filesystems ..."
s3files=$(aws s3files list-file-systems --region "$REGION" \
  --query 'fileSystems[?tags[?key==`Project` && value==`s3-files-benchmark`]].fileSystemId' \
  --output text 2>/dev/null || true)
empty_or_none "$s3files" && note "  (none)" || fail "  S3Files: $s3files"

# 5. EFS filesystems
note "EFS filesystems tagged $TAG_KEY=$TAG_VAL ..."
efs=$(aws efs describe-file-systems --region "$REGION" \
  --query "FileSystems[?Tags[?Key=='$TAG_KEY' && Value=='$TAG_VAL']].FileSystemId" \
  --output text 2>/dev/null || true)
empty_or_none "$efs" && note "  (none)" || fail "  EFS: $efs"

# 6. SageMaker training jobs
note "SageMaker InProgress training jobs ..."
sm=$(aws sagemaker list-training-jobs --region "$REGION" \
  --status-equals InProgress --max-results 50 \
  --query 'TrainingJobSummaries[?starts_with(TrainingJobName, `s3files-bench-`)].TrainingJobName' \
  --output text 2>/dev/null || true)
empty_or_none "$sm" && note "  (none)" || fail "  SM: $sm"

# 7. Lambdas (cleanup, budget-trigger)
note "Lambdas with project name ..."
lambdas=$(aws lambda list-functions --region "$REGION" \
  --query "Functions[?contains(FunctionName,'S3FilesBenchmark')].FunctionName" \
  --output text 2>/dev/null || true)
empty_or_none "$lambdas" && note "  (none)" || fail "  Lambda: $lambdas"

if [[ "$LEFT" -eq 0 ]]; then
  echo "[verify] CLEAN - no leftover resources"
  exit 0
fi
echo "[verify] $LEFT leftover resource group(s) - manual cleanup required"
exit 1
