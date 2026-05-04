# S3 Files Benchmark

3-way cold-cache benchmark — S3 Files vs Mountpoint for S3 vs EFS Standard — under simulated ML/AI workload (fio profiles).

**Spec**: [`docs/superpowers/specs/2026-05-04-s3-files-benchmark-design.md`](../../docs/superpowers/specs/2026-05-04-s3-files-benchmark-design.md)

**Status**: 진행 중 (Ralph Loop 자율 실행)

## Quick start

```bash
# Region override (spec uses us-east-1)
export AWS_REGION=us-east-1

# 1. Deploy infra (idempotent)
make deploy

# 2. SageMaker compatibility PoC
make run-sm

# 3. EC2 fio sweep (auto-triggers via UserData; manual trigger if needed)
make run-ec2

# 4. Collect results from EFS
make collect

# 5. Analyze + render charts
make analyze

# 6. Destroy + verify
make destroy
make verify-clean
```

## Layout

```
.
├── Makefile               # see `make help`
├── cdk/                   # AWS CDK (TypeScript)
│   ├── bin/app.ts
│   └── lib/
│       ├── network-stack.ts     # VPC + SG (NFS 2049)
│       ├── storage-stack.ts     # S3 Files, EFS, S3 bucket
│       ├── client-stack.ts      # c6gn.xlarge Spot EC2
│       ├── cleanup-stack.ts     # 24h auto-destroy Lambda (REQUIRED)
│       └── budget-stack.ts      # $5/day Budget + auto-destroy hook
├── scripts/               # EC2 in-instance shell scripts
├── fio/                   # 4 fio profiles (P1-P4)
├── sagemaker/             # Phase 1 mount compatibility PoC
├── analysis/              # parse + plot
└── output/raw/            # fio JSON, mpstat raw
```

## Cost guard

- Hard cap: **$10/session** (spec)
- Daily Budget alert: **$5** triggers SNS + auto-destroy Lambda
- 24h auto-destroy Lambda runs even if `make destroy` is forgotten

## Hypotheses

- **H1**: cold-cache 4KB random read p50 > 1ms on all three systems (AWS marketing is warm-only)
- **H2**: S3 Files cold seq read significantly slower than EFS Standard, similar to Mountpoint
- **H3**: SageMaker Training Job (Spot) cannot mount S3 Files without explicit VPC + IAM + amazon-efs-utils

Results land in [`docs/research/s3-files.md`](../../docs/research/s3-files.md) once the run completes.
