"""Launch SageMaker Training Job cells T1-T4 to test S3 Files mount compatibility.

Run from local workstation after PHASE 2 deploy:
    python sagemaker/launch_t1_t4.py

Reads CFN outputs to discover subnet, SGs, S3 Files / EFS / bucket IDs.
Submits 4 Spot training jobs with managed_spot_training=True. Each job runs
train.py which only attempts to mount and reports outcomes — no real training.
Total expected cost <$1.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

import boto3

REGION = os.environ.get('AWS_REGION', 'us-east-1')
PROJECT_TAG = 's3-files-benchmark'

CELLS = [
    # (cell_id, instance_type, vpc_mode, max_run_s)
    ('T1', 'ml.m5.xlarge', False, 1800),
    ('T2', 'ml.m5.xlarge', True, 1800),
    ('T3', 'ml.g5.xlarge', True, 1800),
    ('T4', 'ml.m5.xlarge', True, 300),
]


def cfn_outputs(stack_name: str) -> dict[str, str]:
    cf = boto3.client('cloudformation', region_name=REGION)
    r = cf.describe_stacks(StackName=stack_name)
    return {o['OutputKey']: o['OutputValue'] for o in r['Stacks'][0].get('Outputs', [])}


def upload_source(bucket: str, prefix: str = 's3files-bench-poc') -> str:
    """Tar this directory and upload to S3, returning the s3 URI."""
    here = Path(__file__).resolve().parent
    import tarfile
    import io
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for f in ('train.py', 'entry_point.sh', 'requirements.txt'):
            tar.add(here / f, arcname=f)
    buf.seek(0)
    key = f'{prefix}/sourcedir.tar.gz'
    s3 = boto3.client('s3', region_name=REGION)
    s3.upload_fileobj(buf, bucket, key)
    return f's3://{bucket}/{key}'


def make_role_arn() -> str:
    """Resolve a SageMaker execution role from environment or default name."""
    role = os.environ.get('SAGEMAKER_ROLE_ARN')
    if role:
        return role
    sts = boto3.client('sts', region_name=REGION)
    account = sts.get_caller_identity()['Account']
    # Default name — caller may need to create this role manually before T1-T4
    return f'arn:aws:iam::{account}:role/SageMakerExecutionRole-S3FilesBench'


def submit(cell_id: str, instance_type: str, vpc_mode: bool, max_run_s: int,
           role_arn: str, output_bucket: str, source_uri: str,
           network: dict, storage: dict) -> str:
    sm = boto3.client('sagemaker', region_name=REGION)
    job_name = f's3files-bench-{cell_id.lower()}-{int(time.time())}'

    env = {
        'CELL_ID': cell_id,
        'AWS_REGION': REGION,
        'S3FILES_FS_ID': storage.get('S3FilesFileSystemIdOut', ''),
        'EFS_FS_ID': storage.get('EfsFileSystemIdOut', ''),
        'BUCKET_B': storage.get('BucketBName', ''),
        'SAGEMAKER_PROGRAM': 'entry_point.sh',
    }

    config: dict = {
        'TrainingJobName': job_name,
        'AlgorithmSpecification': {
            # Ubuntu DLC python 3.11 base — adjust as needed
            'TrainingImage': f'763104351884.dkr.ecr.{REGION}.amazonaws.com/pytorch-training:2.4.0-cpu-py311-ubuntu22.04-sagemaker',
            'TrainingInputMode': 'File',
            'EnableSageMakerMetricsTimeSeries': False,
        },
        'RoleArn': role_arn,
        'OutputDataConfig': {'S3OutputPath': f's3://{output_bucket}/sagemaker-output/'},
        'ResourceConfig': {
            'InstanceType': instance_type,
            'InstanceCount': 1,
            'VolumeSizeInGB': 30,
        },
        'StoppingCondition': {
            'MaxRuntimeInSeconds': max_run_s,
            'MaxWaitTimeInSeconds': max_run_s + 1800,
        },
        'EnableManagedSpotTraining': True,
        'HyperParameters': {'sagemaker_program': '"entry_point.sh"', 'sagemaker_submit_directory': f'"{source_uri}"'},
        'Environment': env,
        'Tags': [{'Key': 'Project', 'Value': PROJECT_TAG}, {'Key': 'Cell', 'Value': cell_id}],
    }

    if cell_id == 'T3':
        config['AlgorithmSpecification']['TrainingImage'] = (
            f'763104351884.dkr.ecr.{REGION}.amazonaws.com/'
            'pytorch-training:2.4.0-gpu-py311-cu121-ubuntu22.04-sagemaker'
        )

    if vpc_mode:
        config['VpcConfig'] = {
            'SecurityGroupIds': [network['NfsSecurityGroupId']],
            'Subnets': [network['PublicSubnetId']],
        }

    sm.create_training_job(**config)
    return job_name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--cells', nargs='*', default=[c[0] for c in CELLS])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    network = cfn_outputs('S3FilesBenchmark-Network')
    storage = cfn_outputs('S3FilesBenchmark-Storage')
    output_bucket = storage['BucketAName']  # reuse bucketA for SM output

    if args.dry_run:
        print(f'dry-run; resolved network={network}, storage={storage}')
        return

    role_arn = make_role_arn()
    source_uri = upload_source(output_bucket)
    print(f'source uploaded: {source_uri}')

    submitted: dict[str, str] = {}
    for cell_id, instance_type, vpc, max_run_s in CELLS:
        if cell_id not in args.cells:
            continue
        print(f'submitting {cell_id} {instance_type} vpc={vpc} max_run={max_run_s}s')
        try:
            job = submit(cell_id, instance_type, vpc, max_run_s, role_arn,
                         output_bucket, source_uri, network, storage)
            submitted[cell_id] = job
            print(f'  -> {job}')
        except Exception as e:
            submitted[cell_id] = f'SUBMIT_FAILED: {e}'
            print(f'  !! {e}', file=sys.stderr)

    Path(__file__).parent.joinpath('submitted_jobs.json').write_text(json.dumps(submitted, indent=2))
    print(json.dumps(submitted, indent=2))


if __name__ == '__main__':
    main()
