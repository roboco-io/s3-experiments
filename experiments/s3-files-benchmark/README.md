# S3 Files Benchmark

3-way cold-cache benchmark — **S3 Files vs Mountpoint for S3 vs EFS Standard** — under simulated ML/AI workload (fio profiles).

**Spec**: [`docs/superpowers/specs/2026-05-04-s3-files-benchmark-design.md`](../../docs/superpowers/specs/2026-05-04-s3-files-benchmark-design.md) (with Amendment 1: S3 Files API/CFN verification)

**Status**: PHASE 1 (code authoring) ✅ complete. PHASE 2 (deploy + run) awaits user approval.

## Hypotheses
- **H1**: cold-cache 4KB random read p50 > 1ms on all three systems (AWS marketing is warm-only)
- **H2**: S3 Files cold seq read significantly slower than EFS Standard, similar to Mountpoint
- **H3**: SageMaker Training Job (Spot) cannot mount S3 Files without explicit VPC + IAM + amazon-efs-utils

## PHASE 2 — manual launch (cost incurred)

```bash
cd experiments/s3-files-benchmark
export AWS_REGION=us-east-1

# 1. Deploy 5 stacks (Network → Storage → Client → Cleanup → Budget)
#    Cleanup stack MUST be deployed (24h auto-destroy Lambda safety net).
make deploy

# 2. Generate /etc/s3files-bench.env on the EC2 client (via SSM)
INSTANCE_ID=$(aws ec2 describe-instances --region "$AWS_REGION" \
  --filters Name=tag:Project,Values=s3-files-benchmark \
            Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
aws ssm send-command --region "$AWS_REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["bash /home/ec2-user/scripts/05_load_env.sh"]'
# (scripts/ tarball must be uploaded to /home/ec2-user/scripts/ first;
#  see make seed below for the helper)

# 3. SageMaker compatibility PoC (T1–T4)
#    Reads CFN outputs to discover subnet/SG/FS-IDs.
make run-sm     # ~$1, 4 Spot training jobs

# 4. EC2 fio sweep (36 cells, ~2.5h on c6gn.xlarge Spot)
#    UserData triggers 50_run_all.sh once scripts arrive.
make run-ec2

# 5. Pull raw output from EFS to local output/raw/
make collect

# 6. Render summary.csv + charts
make analyze
#  → output/summary.csv, latency_boxplot.png, throughput_bar.png

# 7. Tear down + verify clean
make destroy
make verify-clean   # exits non-zero if anything is left
```

## Cost guard
- Hard cap: **$10/session** (spec section 5.4)
- Daily Budget: **$5** triggers SNS → Lambda → cleanup-lambda forced-destroy
- 24h auto-destroy Lambda runs even if `make destroy` is forgotten
- AL2023 ARM AMI on c6gn.xlarge **Spot** (~$0.030/h)

## Layout

```
.
├── Makefile               # see `make help`
├── cdk/                   # AWS CDK (TypeScript) — npm install && npx cdk synth --all OK
│   ├── bin/app.ts         # wires 5 stacks
│   └── lib/
│       ├── network-stack.ts     # single-AZ public-only VPC, NFS 2049 SG
│       ├── storage-stack.ts     # bucket A/B + S3 Files (CfnResource L1) + EFS
│       ├── client-stack.ts      # c6gn.xlarge Spot via LaunchTemplate
│       ├── cleanup-stack.ts     # 24h auto-destroy Lambda (REQUIRED)
│       └── budget-stack.ts      # $5/day Budget + SNS + Lambda hook
├── scripts/               # EC2 in-instance shell (sourced via common.sh)
│   ├── 00_install.sh      # fio, sysstat, jq, amazon-efs-utils, mount-s3
│   ├── 05_load_env.sh     # CFN outputs → /etc/s3files-bench.env
│   ├── 10_mount_all.sh    # 3 filesystems (idempotent)
│   ├── 20_seed.sh         # fio --create_only=1 per profile per system
│   ├── 30_cold_setup.sh   # umount/remount + drop_caches per system
│   ├── 40_run_one.sh      # one (run, system, profile) cell + mpstat + fallback
│   ├── 45_save_checkpoint.sh # IMDS spot interruption guard
│   ├── 50_run_all.sh      # orchestrate 36 cells, resumable
│   ├── 90_destroy.sh      # local mount cleanup
│   ├── 99_verify_clean.sh # grep AWS for leftovers tagged Project=...
│   └── collect_results.sh # SSM tarball pull from EFS
├── fio/                   # 4 profiles (P1 shard-seq-read, P2 random-4k, P3 ckpt-write, P4 mixed)
├── sagemaker/             # T1–T4 mount compatibility PoC + boto3 launcher
├── analysis/              # parse_fio.py → summary.csv; plots.py → 2 PNGs; compare_table.py → md
└── output/                # raw/, summary.csv, *.png — gitignored
```

## Verified spec gaps
- AWS CLI 2.34.41+ is required (s3files subcommand)
- AWS::S3Files::FileSystem and AWS::S3Files::MountTarget are PUBLIC LIVE CFN resources (verified via describe-type)
- aws-cdk-lib 2.252.0 has no L2 construct for S3 Files; we use `cdk.CfnResource` directly per Amendment 1

## After PHASE 2 completes
Findings land in [`docs/research/s3-files.md`](../../docs/research/s3-files.md) and updates flow back to:
- [`docs/research/file-io.md`](../../docs/research/file-io.md) — table 2.3 (latency), 6.2 (locking)
- root README pattern 5 row
