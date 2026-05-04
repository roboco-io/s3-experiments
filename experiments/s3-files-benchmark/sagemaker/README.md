# SageMaker S3 Files Mount Compatibility PoC

Phase 1 of the experiment per spec section 4.1. Goal: determine whether S3 Files
can be mounted from inside a SageMaker Training Job (Spot), and document the
exact constraints (VPC mode, IAM, packages, kernel modules).

## Prerequisites
- Phase 2 CDK deployed (S3FilesBenchmark-{Network,Storage,Client,Cleanup,Budget})
- SageMaker execution role exists (default: `SageMakerExecutionRole-S3FilesBench`).
  Override via `SAGEMAKER_ROLE_ARN` env var.

## Run

```bash
# All four cells
python launch_t1_t4.py

# Single cell
python launch_t1_t4.py --cells T2

# Dry-run (resolve CFN outputs only, no submit)
python launch_t1_t4.py --dry-run
```

Each job uploads `mount_attempt.json` to `s3://<bucketA>/sagemaker-output/<job>/output/output.tar.gz`.
Pull and inspect via `aws s3 cp` then untar.

## Cell matrix

| Cell | Instance     | VPC Mode | Max run | Hypothesis                                         |
|------|--------------|----------|---------|----------------------------------------------------|
| T1   | ml.m5.xlarge | OFF      | 30 min  | Expected fail — SageMaker default has no VPC route |
| T2   | ml.m5.xlarge | ON       | 30 min  | Most likely to succeed — DLC + amazon-efs-utils    |
| T3   | ml.g5.xlarge | ON       | 30 min  | GPU container — verify same path works             |
| T4   | ml.m5.xlarge | ON       | 5 min   | Spot interruption corner case observation          |

## Results (filled by PHASE 2 after submission)

| Cell | Job Name | Mount rc | Stderr (excerpt) | Status                        |
|------|----------|----------|------------------|-------------------------------|
| T1   | TBD      | TBD      | TBD              | NOT YET RUN                   |
| T2   | TBD      | TBD      | TBD              | NOT YET RUN                   |
| T3   | TBD      | TBD      | TBD              | NOT YET RUN                   |
| T4   | TBD      | TBD      | TBD              | NOT YET RUN                   |

Verbatim error logs and IAM/SG diagnostics will be appended below the table
once the cells run.
