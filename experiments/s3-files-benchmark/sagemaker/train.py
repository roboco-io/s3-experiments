"""S3 Files mount-attempt PoC for SageMaker Training Job.

Does NOT train anything. Only attempts to:
1. Install amazon-efs-utils + mount-s3 if missing
2. Mount the S3 Files filesystem (or report failure verbatim)
3. Mount EFS (sanity baseline — should always work in VPC mode)
4. Mount Mountpoint for S3 (sanity baseline)
5. Capture errno, mount table, kernel module presence, IAM identity

Writes a JSON report to /opt/ml/output/data/mount_attempt.json which SageMaker
uploads to s3://<output-bucket>/<job-name>/output/output.tar.gz on completion.
"""
from __future__ import annotations
import json
import os
import subprocess
import shlex
import time
from pathlib import Path

OUTPUT_DIR = Path('/opt/ml/output/data')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT = OUTPUT_DIR / 'mount_attempt.json'

S3FILES_FS_ID = os.environ.get('S3FILES_FS_ID', '')
EFS_FS_ID = os.environ.get('EFS_FS_ID', '')
BUCKET_B = os.environ.get('BUCKET_B', '')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
CELL_ID = os.environ.get('CELL_ID', 'unknown')


def run(cmd: str | list[str], timeout: int = 60) -> dict:
    """Run a shell command and capture rc/stdout/stderr (truncated)."""
    if isinstance(cmd, str):
        argv = shlex.split(cmd)
    else:
        argv = cmd
    started = time.time()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return {
            'cmd': argv,
            'rc': p.returncode,
            'stdout': p.stdout[:2000],
            'stderr': p.stderr[:2000],
            'duration_s': round(time.time() - started, 2),
        }
    except subprocess.TimeoutExpired as e:
        return {'cmd': argv, 'rc': -1, 'stderr': f'timeout after {timeout}s: {e}', 'duration_s': timeout}
    except Exception as e:
        return {'cmd': argv, 'rc': -2, 'stderr': repr(e), 'duration_s': round(time.time() - started, 2)}


def main() -> None:
    report: dict = {
        'cell_id': CELL_ID,
        's3files_fs_id': S3FILES_FS_ID,
        'efs_fs_id': EFS_FS_ID,
        'bucket_b': BUCKET_B,
        'region': AWS_REGION,
        'environment': {k: v for k, v in os.environ.items() if k.startswith(('SM_', 'AWS_'))},
    }

    # Pre-mount diagnostics
    report['preflight'] = {
        'whoami': run('whoami'),
        'kernel': run('uname -a'),
        'lsmod_nfs': run('lsmod | grep -E "^nfs|^nfsv4"'),
        'iam_identity': run(f'aws sts get-caller-identity --region {AWS_REGION}'),
        'has_mount_t_s3files': run('mount --help'),  # check for s3files type support
        'amazon_efs_utils_rpm': run('rpm -q amazon-efs-utils'),
    }

    # Try installing amazon-efs-utils if not present
    if report['preflight']['amazon_efs_utils_rpm']['rc'] != 0:
        report['install_efs_utils'] = run('yum -y install amazon-efs-utils', timeout=120)

    # Mount points
    for mp in ('/mnt/s3files', '/mnt/efs', '/mnt/mountpoint'):
        Path(mp).mkdir(parents=True, exist_ok=True)

    # Mount attempts
    if S3FILES_FS_ID:
        report['mount_s3files'] = run(f'mount -t s3files {S3FILES_FS_ID}:/ /mnt/s3files')
        report['ls_s3files'] = run('ls -la /mnt/s3files')

    if EFS_FS_ID:
        report['mount_efs'] = run(f'mount -t efs -o tls {EFS_FS_ID}:/ /mnt/efs')
        report['ls_efs'] = run('ls -la /mnt/efs')

    if BUCKET_B and Path('/usr/bin/mount-s3').exists():
        report['mount_mountpoint'] = run(f'mount-s3 {BUCKET_B} /mnt/mountpoint --no-cache --allow-other --region {AWS_REGION}')
        report['ls_mountpoint'] = run('ls -la /mnt/mountpoint')

    report['mount_table'] = run('mount')

    REPORT.write_text(json.dumps(report, indent=2))
    print(f'wrote {REPORT}')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
