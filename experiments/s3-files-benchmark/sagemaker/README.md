# SageMaker S3 Files Mount Compatibility PoC — Results

Phase 2 result, 2026-05-04. Spec section 4.1 / hypothesis H3.

## Verdict

**H3 confirmed (decisively negative): SageMaker Training Job containers cannot mount S3 Files (or EFS) regardless of VPC mode, IAM permissions, or package installation effort.**

All three submitted cells failed with identical `mount: ... permission denied (rc=32)`. Root cause is structural, not configurable away from inside a training job.

## Cell results

| Cell | Job Name | Instance | VPC | mount -t s3files | mount -t efs | mount-s3 (FUSE) |
|---|---|---|---|---|---|---|
| T1 | `s3files-bench-t1-1777872374` | ml.m5.xlarge Spot | OFF | rc=32 permission denied | rc=32 permission denied | install failed (no apt+rpm path) |
| T2 | `s3files-bench-t2-1777872375` | ml.m5.xlarge Spot | ON (subnet+SG) | rc=32 permission denied | rc=32 permission denied | install failed |
| T3 | NOT SUBMITTED | ml.g5.xlarge Spot | ON | — | — | — |
| T4 | `s3files-bench-t4-1777872383` | ml.m5.xlarge Spot, max_run=300s | ON | rc=32 permission denied | rc=32 permission denied | install failed |

T3 was rejected at submit time: `ResourceLimitExceeded: account-level service limit 'ml.g5.xlarge for spot training job usage' is 0 Instances`. Would require AWS Service Quotas request to enable. Skipped — VPC + Linux container context is the same as T2/T3 GPU difference does not bear on H3.

## Root cause (verbatim diagnostics from T2 preflight)

```
whoami:                  root
kernel:                  Linux ... 5.10.252-250.1005.amzn2.x86_64 ... x86_64
lsmod | grep nfs:        (empty — NFS modules NOT loaded in container)
amazon-efs-utils RPM:    rc=-2 (FileNotFoundError — `rpm` command absent)
install yum -y efs-utils: rc=-2 (FileNotFoundError — `yum` command absent)
container rootfs:        overlay on / (Docker overlay2) — kernel-namespace isolated
container distro:        Ubuntu 22.04 (DLC pytorch-training:2.4.0-cpu-py311-ubuntu22.04-sagemaker)
```

Three independent blockers, any one of which would suffice:

1. **No NFS kernel modules** loaded in the container's kernel namespace. `mount -t nfs4` / `mount -t s3files` (which uses NFS via amazon-efs-utils) requires the host kernel to have NFS modules. SageMaker training containers run on a host that may or may not have them, and even if loaded on host, the container can't unprivilegedly request them.
2. **No mount privilege**. SageMaker training jobs do not run with `--privileged`, `CAP_SYS_ADMIN`, or `--device`. A non-privileged container cannot perform NFS-style mounts.
3. **Wrong distro/package manager**. AWS DLC pytorch CPU image is Ubuntu 22.04. Our entry script tried `yum`/`dnf` install of `amazon-efs-utils` (which is RPM-only). Even the apt path doesn't exist for `mount-s3` on its standard release channel; you'd need to build from source. None of this matters for #1 and #2.

The "VPC mode" knob (T1 vs T2/T4) had no effect — even with subnet + NFS-2049 SG attached, the mount call fails inside the container before any network egress.

## What this means for ML practitioners
- For SageMaker training, **do not plan to mount S3 Files**. Use the SageMaker `FileSystemConfig` parameter to attach EFS/FSx — these are managed mounts handled outside the container by the platform — or use `S3DataSource` (channel input) for staged data.
- Mountpoint for S3 (FUSE) is **also not viable from inside a training container**: `mount-s3` requires `--cap-add SYS_ADMIN --device /dev/fuse` which SageMaker does not grant. A BYOC image with `mount-s3` baked in still fails at run time with `fuse: device not found`. Documented in [`awslabs/mountpoint-s3#707`](https://github.com/awslabs/mountpoint-s3/issues/707).
- If you need file-system semantics on S3-backed data within SageMaker, the supported path today is **EFS/FSx attached via [`FileSystemConfig`](https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_FileSystemConfig.html) / [`FileSystemDataSource`](https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_FileSystemDataSource.html)**, not user-space mounts. SageMaker mounts these at the host level before the container starts and exposes them at `/opt/ml/input/data/<channel>`.
- S3 Files itself is **not** in the FileSystemDataSource type list as of 2026-05-04 (`EFS` and `FSxLustre` only). To benefit from S3 Files inside a SageMaker job, AWS would need to add it as a supported FileSystemType — this is the right place for that feature request.

## Independent verification (added 2026-05-04 via Perplexity research)

Three independent sources confirm the negative result is structural, not a misconfiguration of our test:

1. **AWS docs** distinguish notebook instances (allow `sudo mount -t nfs` via [lifecycle configs](https://aws.amazon.com/blogs/machine-learning/mount-an-efs-file-system-to-an-amazon-sagemaker-notebook-with-lifecycle-configurations/) because they run as full single-tenant OS) from training containers (multi-tenant Docker, restricted capability set). Our test was on training containers.
2. **GitHub issue [`awslabs/mountpoint-s3#707`](https://github.com/awslabs/mountpoint-s3/issues/707)** documents an identical `fuse: device not found, try 'modprobe fuse' first` from SageMaker, with the maintainers confirming `--cap-add SYS_ADMIN --device /dev/fuse` is required and "may not be supported when using a service like Sagemaker".
3. **GitHub issue [`aws/sagemaker-python-sdk#2204`](https://github.com/aws/sagemaker-python-sdk/issues/2204)** reports the same EFS in-container mount failure that we observed.

[BYOC documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/docker-containers-adapt-your-own.html) does not provide any mechanism to opt into elevated capabilities — the SageMaker Training Toolkit can override the entry point and the framework but not the container runtime configuration. So the conclusion holds for any custom image too.

## Files
- `train.py` — preflight + mount attempts; writes JSON report
- `entry_point.sh` — SM entrypoint (yum/dnf install attempt)
- `launch_t1_t4.py` — boto3 launcher
- raw outputs: not committed (in `s3://s3files-bench-779411790546-a/sagemaker-output/<job>/output/output.tar.gz`)
