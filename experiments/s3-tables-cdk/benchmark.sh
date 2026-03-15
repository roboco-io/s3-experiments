#!/bin/bash
set -e

RUN_ID=$(openssl rand -hex 4)
export RUN_ID

echo "======================================================================"
echo "S3 Tables CDK Benchmark"
echo "  Run ID: $RUN_ID"
echo "  Region: us-east-1"
echo "======================================================================"

# Deploy
echo ""
echo "--- Phase 1: CDK Deploy ---"
npx cdk deploy --context runId=$RUN_ID --require-approval never --outputs-file output/cdk-outputs.json 2>&1

# Extract outputs
TABLE_BUCKET=$(jq -r '.S3TablesBenchmark.TableBucketName' output/cdk-outputs.json)
REGULAR_BUCKET=$(jq -r '.S3TablesBenchmark.RegularBucketName' output/cdk-outputs.json)
GLUE_DB=$(jq -r '.S3TablesBenchmark.GlueDatabaseName' output/cdk-outputs.json)
WORKGROUP=$(jq -r '.S3TablesBenchmark.AthenaWorkgroup' output/cdk-outputs.json)
ATHENA_OUTPUT=$(jq -r '.S3TablesBenchmark.AthenaOutputLocation' output/cdk-outputs.json)

echo ""
echo "Resources deployed:"
echo "  Table Bucket:  $TABLE_BUCKET"
echo "  Regular Bucket: $REGULAR_BUCKET"
echo "  Glue Database:  $GLUE_DB"
echo "  Workgroup:      $WORKGROUP"

# Run benchmark
echo ""
echo "--- Phase 2: Running Benchmark ---"
npx ts-node benchmark.ts \
  --tableBucket "$TABLE_BUCKET" \
  --regularBucket "$REGULAR_BUCKET" \
  --glueDb "$GLUE_DB" \
  --workgroup "$WORKGROUP" \
  --athenaOutput "$ATHENA_OUTPUT" \
  --runId "$RUN_ID"

# Destroy
echo ""
echo "--- Phase 3: CDK Destroy ---"
npx cdk destroy --context runId=$RUN_ID --force 2>&1

echo ""
echo "Benchmark complete. Results in output/"
