"""
S3 Event Notifications 실측 벤치마크
- S3 → Lambda → DynamoDB 파이프라인 자동 구성
- 대량 PutObject 후 전달 보장(중복/유실), 순서, 지연시간 분석
- 완료 후 모든 리소스 자동 삭제
"""

import boto3
import json
import time
import uuid
import zipfile
import io
import statistics
import concurrent.futures
from datetime import datetime, timezone

REGION = "us-east-1"
RUN_ID = uuid.uuid4().hex[:8]
BUCKET_NAME = f"s3dd-evnt-{RUN_ID}"
TABLE_NAME = f"s3dd-evnt-{RUN_ID}"
FUNCTION_NAME = f"s3dd-evnt-{RUN_ID}"
ROLE_NAME = f"s3dd-evnt-{RUN_ID}"

s3 = boto3.client("s3", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)
ddb = boto3.client("dynamodb", region_name=REGION)
iam = boto3.client("iam", region_name=REGION)
sts = boto3.client("sts", region_name=REGION)

ACCOUNT_ID = sts.get_caller_identity()["Account"]

# ============================================================
# Lambda function code (inline)
# ============================================================
LAMBDA_CODE = """
import boto3
import json
import time
import os

ddb = boto3.resource('dynamodb')
table = ddb.Table(os.environ['TABLE_NAME'])

def handler(event, context):
    receive_ts = int(time.time() * 1000)

    for record in event['Records']:
        s3_info = record['s3']
        event_time = record['eventTime']
        sequencer = s3_info['object'].get('sequencer', 'N/A')
        key = s3_info['object']['key']

        table.put_item(Item={
            'pk': f"{key}#{sequencer}#{context.aws_request_id}",
            'object_key': key,
            'sequencer': sequencer,
            'event_time': event_time,
            'receive_timestamp_ms': receive_ts,
            'lambda_request_id': context.aws_request_id,
            'event_name': record['eventName'],
        })

    return {'statusCode': 200}
"""


def create_lambda_zip():
    """Lambda 코드를 zip으로 패키징"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("index.py", LAMBDA_CODE)
    buf.seek(0)
    return buf.read()


def setup():
    """인프라 구성: IAM Role, DynamoDB, Lambda, S3 Bucket + Notification"""
    print("=== Setting up infrastructure ===")

    # 1. IAM Role
    print("  Creating IAM role...", end=" ", flush=True)
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }
    try:
        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
        )
    except iam.exceptions.EntityAlreadyExistsException:
        pass

    # Attach policies
    for policy_arn in [
        "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess",
        "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess",
    ]:
        iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn=policy_arn)
    print("done")

    # 2. DynamoDB Table
    print("  Creating DynamoDB table...", end=" ", flush=True)
    ddb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    waiter = ddb.get_waiter("table_exists")
    waiter.wait(TableName=TABLE_NAME)
    print("done")

    # 3. Wait for IAM role propagation
    print("  Waiting for IAM role propagation (10s)...", end=" ", flush=True)
    time.sleep(10)
    print("done")

    # 4. Lambda Function
    print("  Creating Lambda function...", end=" ", flush=True)
    role_arn = f"arn:aws:iam::{ACCOUNT_ID}:role/{ROLE_NAME}"
    zip_bytes = create_lambda_zip()

    for attempt in range(5):
        try:
            lam.create_function(
                FunctionName=FUNCTION_NAME,
                Runtime="python3.12",
                Role=role_arn,
                Handler="index.handler",
                Code={"ZipFile": zip_bytes},
                Timeout=30,
                MemorySize=256,
                Environment={"Variables": {"TABLE_NAME": TABLE_NAME}},
            )
            break
        except lam.exceptions.InvalidParameterValueException:
            time.sleep(5)  # IAM role not yet available

    # Wait for function to be active
    waiter = lam.get_waiter("function_active_v2")
    waiter.wait(FunctionName=FUNCTION_NAME)
    print("done")

    # 5. Add Lambda permission for S3
    print("  Adding S3 invoke permission...", end=" ", flush=True)
    lam.add_permission(
        FunctionName=FUNCTION_NAME,
        StatementId="s3-invoke",
        Action="lambda:InvokeFunction",
        Principal="s3.amazonaws.com",
        SourceArn=f"arn:aws:s3:::{BUCKET_NAME}",
        SourceAccount=ACCOUNT_ID,
    )
    print("done")

    # 6. S3 Bucket + Event Notification
    print("  Creating S3 bucket with notification...", end=" ", flush=True)
    s3.create_bucket(Bucket=BUCKET_NAME)

    lambda_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{FUNCTION_NAME}"
    s3.put_bucket_notification_configuration(
        Bucket=BUCKET_NAME,
        NotificationConfiguration={
            "LambdaFunctionConfigurations": [{
                "LambdaFunctionArn": lambda_arn,
                "Events": ["s3:ObjectCreated:*"],
                "Filter": {
                    "Key": {"FilterRules": [{"Name": "prefix", "Value": "events/"}]}
                },
            }]
        },
    )
    print("done")
    print()


def run_experiment(event_count, concurrency, label):
    """이벤트 생성 후 결과 분석"""
    print(f"--- Experiment: {label} ({event_count:,} events, concurrency={concurrency}) ---")

    # 이벤트 발행
    send_timestamps = {}  # key -> send_time_ms

    def put_event(seq):
        key = f"events/{seq:06d}.json"
        body = json.dumps({
            "seq": seq,
            "send_ts": int(time.time() * 1000),
            "run_id": RUN_ID,
        })
        ts = int(time.time() * 1000)
        s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=body.encode())
        send_timestamps[key] = ts
        return key

    print(f"  Sending {event_count:,} events...", end=" ", flush=True)
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        list(executor.map(put_event, range(event_count)))
    send_elapsed = time.time() - start
    print(f"done in {send_elapsed:.1f}s ({event_count/send_elapsed:.0f} events/s)")

    # Lambda 처리 대기
    wait_seconds = max(30, event_count // 50)  # 최소 30초, 이벤트 수에 비례
    print(f"  Waiting {wait_seconds}s for Lambda processing...", end=" ", flush=True)
    time.sleep(wait_seconds)
    print("done")

    # DynamoDB에서 결과 수집
    print("  Collecting results from DynamoDB...", end=" ", flush=True)
    items = []
    paginator = ddb.get_paginator("scan")
    for page in paginator.paginate(TableName=TABLE_NAME):
        items.extend(page.get("Items", []))
    print(f"{len(items)} records")

    # ============================================================
    # 분석
    # ============================================================
    print(f"\n  === Analysis: {label} ===")

    # 1. 전달률 (유실 확인)
    received_keys = set()
    for item in items:
        received_keys.add(item["object_key"]["S"])

    sent_keys = set(f"events/{i:06d}.json" for i in range(event_count))
    missing = sent_keys - received_keys
    extra = received_keys - sent_keys
    delivery_rate = len(received_keys & sent_keys) / event_count * 100

    print(f"  [Delivery]")
    print(f"    Sent: {event_count:,}  |  Received: {len(received_keys):,}  |  "
          f"Rate: {delivery_rate:.1f}%")
    if missing:
        print(f"    MISSING ({len(missing)}): {list(missing)[:5]}...")
    else:
        print(f"    No missing events")

    # 2. 중복 확인
    key_counts = {}
    for item in items:
        k = item["object_key"]["S"]
        key_counts[k] = key_counts.get(k, 0) + 1

    duplicates = {k: v for k, v in key_counts.items() if v > 1}
    dup_count = sum(v - 1 for v in duplicates.values())

    print(f"  [Duplicates]")
    print(f"    Total records: {len(items):,}  |  Unique keys: {len(key_counts):,}  |  "
          f"Duplicate deliveries: {dup_count}")
    if duplicates:
        for k, v in list(duplicates.items())[:3]:
            print(f"      {k}: delivered {v} times")
    else:
        print(f"    No duplicates detected")

    # 3. 순서 분석
    # sequencer 기반 순서 vs 실제 도착 순서
    records_by_key = []
    for item in items:
        key = item["object_key"]["S"]
        seq_num = int(key.split("/")[1].split(".")[0])  # events/000042.json -> 42
        records_by_key.append({
            "seq": seq_num,
            "sequencer": item["sequencer"]["S"],
            "receive_ts": int(item["receive_timestamp_ms"]["N"]),
        })

    records_by_key.sort(key=lambda x: x["receive_ts"])

    # 순서 역전 카운트
    inversions = 0
    for i in range(1, len(records_by_key)):
        if records_by_key[i]["seq"] < records_by_key[i-1]["seq"]:
            inversions += 1

    inversion_rate = inversions / max(1, len(records_by_key) - 1) * 100

    print(f"  [Ordering]")
    print(f"    Order inversions: {inversions:,} / {len(records_by_key)-1:,} "
          f"({inversion_rate:.1f}%)")
    if inversions > 0:
        print(f"    >> Events are NOT delivered in order (as documented)")

    # sequencer 순서 분석
    records_sorted_seq = sorted(records_by_key, key=lambda x: x["sequencer"])
    seq_inversions = 0
    for i in range(1, len(records_sorted_seq)):
        if records_sorted_seq[i]["seq"] < records_sorted_seq[i-1]["seq"]:
            seq_inversions += 1

    print(f"    Sequencer-based inversions: {seq_inversions:,} "
          f"(sequencer field preserves order: {'YES' if seq_inversions == 0 else 'NO'})")

    # 4. 지연시간 분석
    latencies = []
    for item in items:
        key = item["object_key"]["S"]
        if key in send_timestamps:
            recv = int(item["receive_timestamp_ms"]["N"])
            send = send_timestamps[key]
            lat = recv - send
            if lat > 0:
                latencies.append(lat)

    if latencies:
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]
        avg = statistics.mean(latencies)
        max_lat = max(latencies)
        min_lat = min(latencies)

        print(f"  [Latency (S3 PUT → Lambda receive)]")
        print(f"    min={min_lat}ms  avg={avg:.0f}ms  p50={p50}ms  "
              f"p95={p95}ms  p99={p99}ms  max={max_lat}ms")
    else:
        print(f"  [Latency] Could not compute (timestamp mismatch)")

    # DynamoDB 테이블 비우기 (다음 실험을 위해)
    print(f"  Clearing DynamoDB table...", end=" ", flush=True)
    for item in items:
        ddb.delete_item(TableName=TABLE_NAME, Key={"pk": item["pk"]})
    print("done")

    # S3 객체 삭제
    print(f"  Clearing S3 objects...", end=" ", flush=True)
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix="events/"):
        if "Contents" in page:
            objects = [{"Key": obj["Key"]} for obj in page["Contents"]]
            s3.delete_objects(Bucket=BUCKET_NAME, Delete={"Objects": objects})
    print("done\n")

    return {
        "label": label,
        "event_count": event_count,
        "concurrency": concurrency,
        "send_elapsed_s": round(send_elapsed, 2),
        "delivery_rate_pct": round(delivery_rate, 2),
        "total_records": len(items),
        "unique_keys": len(key_counts),
        "duplicate_deliveries": dup_count,
        "missing_count": len(missing),
        "order_inversions": inversions,
        "inversion_rate_pct": round(inversion_rate, 2),
        "sequencer_preserves_order": seq_inversions == 0,
        "latency": {
            "min_ms": min_lat if latencies else None,
            "avg_ms": round(avg) if latencies else None,
            "p50_ms": p50 if latencies else None,
            "p95_ms": p95 if latencies else None,
            "p99_ms": p99 if latencies else None,
            "max_ms": max_lat if latencies else None,
        }
    }


def teardown():
    """모든 리소스 삭제"""
    print("=== Tearing down infrastructure ===")

    # S3 objects + bucket
    print("  Deleting S3 bucket...", end=" ", flush=True)
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET_NAME):
            if "Contents" in page:
                objects = [{"Key": obj["Key"]} for obj in page["Contents"]]
                s3.delete_objects(Bucket=BUCKET_NAME, Delete={"Objects": objects})
        s3.delete_bucket(Bucket=BUCKET_NAME)
        print("done")
    except Exception as e:
        print(f"error: {e}")

    # Lambda
    print("  Deleting Lambda function...", end=" ", flush=True)
    try:
        lam.delete_function(FunctionName=FUNCTION_NAME)
        print("done")
    except Exception as e:
        print(f"error: {e}")

    # DynamoDB
    print("  Deleting DynamoDB table...", end=" ", flush=True)
    try:
        ddb.delete_table(TableName=TABLE_NAME)
        print("done")
    except Exception as e:
        print(f"error: {e}")

    # IAM Role (detach policies first)
    print("  Deleting IAM role...", end=" ", flush=True)
    try:
        for policy_arn in [
            "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
            "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess",
            "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess",
        ]:
            iam.detach_role_policy(RoleName=ROLE_NAME, PolicyArn=policy_arn)
        iam.delete_role(RoleName=ROLE_NAME)
        print("done")
    except Exception as e:
        print(f"error: {e}")


def main():
    print("=" * 70)
    print("S3 Event Notifications Benchmark")
    print(f"  Delivery guarantee: at-least-once? Ordering? Latency?")
    print(f"  Run ID: {RUN_ID}  Region: {REGION}")
    print(f"  Time: {datetime.now().isoformat()}")
    print("=" * 70 + "\n")

    all_results = {
        "run_id": RUN_ID,
        "region": REGION,
        "timestamp": datetime.now().isoformat(),
        "experiments": []
    }

    setup()

    try:
        # 실험 1: 소규모 (100 events, 순차)
        r1 = run_experiment(100, concurrency=1, label="100 events, sequential")
        all_results["experiments"].append(r1)

        # 실험 2: 중규모 (500 events, 병렬 10)
        r2 = run_experiment(500, concurrency=10, label="500 events, concurrency=10")
        all_results["experiments"].append(r2)

        # 실험 3: 대규모 (2000 events, 병렬 50)
        r3 = run_experiment(2000, concurrency=50, label="2000 events, concurrency=50")
        all_results["experiments"].append(r3)

        # 요약
        print("=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"\n{'Experiment':<35} {'Sent':>6} {'Recv':>6} {'Dup':>5} {'Miss':>5} "
              f"{'Inversions':>11} {'p50(ms)':>8} {'p99(ms)':>8}")
        print("-" * 95)
        for r in all_results["experiments"]:
            lat = r["latency"]
            print(f"{r['label']:<35} {r['event_count']:>6} {r['unique_keys']:>6} "
                  f"{r['duplicate_deliveries']:>5} {r['missing_count']:>5} "
                  f"{r['order_inversions']:>5} ({r['inversion_rate_pct']:>4.1f}%) "
                  f"{lat['p50_ms'] or 'N/A':>8} {lat['p99_ms'] or 'N/A':>8}")

        print(f"\nSequencer preserves order: "
              f"{all(r['sequencer_preserves_order'] for r in all_results['experiments'])}")

        # 결과 저장
        import os
        os.makedirs("output", exist_ok=True)
        with open("output/results.json", "w") as f:
            json.dump(all_results, f, indent=2, default=str)
        print(f"\nResults saved to output/results.json")

    finally:
        teardown()


if __name__ == "__main__":
    main()
