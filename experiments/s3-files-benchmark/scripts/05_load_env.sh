#!/bin/bash
# 05_load_env.sh — generate /etc/s3files-bench.env from CloudFormation outputs.
# Run as root on the EC2 client (or locally with the same AWS profile).
set -euxo pipefail

REGION="${AWS_REGION:-us-east-1}"
ENV_FILE="${ENV_FILE:-/etc/s3files-bench.env}"

cfn_out() {
  local stack="$1" key="$2"
  aws cloudformation describe-stacks \
    --stack-name "$stack" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$key'].OutputValue|[0]" \
    --output text
}

BUCKET_A=$(cfn_out S3FilesBenchmark-Storage BucketAName)
BUCKET_B=$(cfn_out S3FilesBenchmark-Storage BucketBName)
S3FILES_FS_ID=$(cfn_out S3FilesBenchmark-Storage S3FilesFileSystemIdOut)
EFS_FS_ID=$(cfn_out S3FilesBenchmark-Storage EfsFileSystemIdOut)

cat > "$ENV_FILE" <<EOF
# Generated $(date -u +%FT%TZ) by 05_load_env.sh
BUCKET_A=$BUCKET_A
BUCKET_B=$BUCKET_B
S3FILES_FS_ID=$S3FILES_FS_ID
EFS_FS_ID=$EFS_FS_ID
AWS_REGION=$REGION
EOF
chmod 644 "$ENV_FILE"
echo "[05_load_env] wrote $ENV_FILE:"
cat "$ENV_FILE"
