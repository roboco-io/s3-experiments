"""
S3 파일 리스팅/검색 성능 벤치마크
- 다양한 파일 수 (100, 1K, 10K, 50K)에서 ListObjectsV2 성능 측정
- HeadObject (존재 확인) 지연 측정
- GetObject 지연 측정 (파일 크기별)
- 프리픽스 기반 필터링 성능
"""

import boto3
import time
import json
import uuid
import hashlib
import statistics
import concurrent.futures
from datetime import datetime

BUCKET_NAME = f"s3-deep-dive-bench-{uuid.uuid4().hex[:8]}"
REGION = "us-east-1"

s3 = boto3.client("s3", region_name=REGION)


def create_bucket():
    """벤치마크용 버킷 생성"""
    try:
        s3.create_bucket(Bucket=BUCKET_NAME)
        print(f"Bucket created: {BUCKET_NAME}")
    except Exception as e:
        print(f"Bucket creation: {e}")


def delete_bucket():
    """벤치마크용 버킷 삭제 (모든 객체 포함)"""
    print("\nCleaning up...")
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET_NAME):
        if "Contents" in page:
            objects = [{"Key": obj["Key"]} for obj in page["Contents"]]
            s3.delete_objects(Bucket=BUCKET_NAME, Delete={"Objects": objects})
    s3.delete_bucket(Bucket=BUCKET_NAME)
    print(f"Bucket deleted: {BUCKET_NAME}")


def upload_files(count, prefix="files", value_size=1024):
    """파일 업로드 (병렬)"""
    print(f"  Uploading {count:,} files (prefix={prefix}, size={value_size}B)...", end=" ", flush=True)
    start = time.time()
    data = b"x" * value_size

    def put_one(i):
        key = f"{prefix}/{hashlib.md5(str(i).encode()).hexdigest()[:4]}/file-{i:08d}.dat"
        s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=data)
        return key

    keys = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        keys = list(executor.map(put_one, range(count)))

    elapsed = time.time() - start
    print(f"done in {elapsed:.1f}s ({count/elapsed:.0f} files/s)")
    return keys


def bench_list_all(prefix="files", label=""):
    """ListObjectsV2로 전체 리스팅 시간 측정"""
    results = []
    for trial in range(3):
        start = time.time()
        total = 0
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=prefix):
            total += page.get("KeyCount", 0)
        elapsed = time.time() - start
        results.append({"elapsed_s": elapsed, "object_count": total})

    avg = statistics.mean([r["elapsed_s"] for r in results])
    count = results[0]["object_count"]
    print(f"  ListObjectsV2 {label}({count:,} objects): avg {avg:.3f}s  "
          f"({count/avg:.0f} objects/s)")
    return {"operation": "ListObjectsV2", "label": label, "object_count": count,
            "avg_s": round(avg, 4), "trials": results}


def bench_list_prefix_filter(prefix="files", sub_prefix_count=5):
    """프리픽스 필터링 리스팅 (특정 프리픽스만)"""
    # 첫 N개 해시 프리픽스만 조회
    results = []
    prefixes_to_check = [f"{prefix}/{hashlib.md5(str(i).encode()).hexdigest()[:4]}/"
                         for i in range(sub_prefix_count)]

    for trial in range(3):
        start = time.time()
        total = 0
        for p in prefixes_to_check:
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=p):
                total += page.get("KeyCount", 0)
        elapsed = time.time() - start
        results.append({"elapsed_s": elapsed, "object_count": total})

    avg = statistics.mean([r["elapsed_s"] for r in results])
    count = results[0]["object_count"]
    print(f"  ListObjectsV2 prefix-filter ({count:,} objects, {sub_prefix_count} prefixes): "
          f"avg {avg:.3f}s")
    return {"operation": "ListObjectsV2-prefix-filter", "object_count": count,
            "prefix_count": sub_prefix_count, "avg_s": round(avg, 4), "trials": results}


def bench_head_object(keys, count=100):
    """HeadObject (파일 존재 확인) 지연 측정"""
    import random
    sample = random.sample(keys, min(count, len(keys)))
    latencies = []

    for key in sample:
        start = time.time()
        s3.head_object(Bucket=BUCKET_NAME, Key=key)
        latencies.append((time.time() - start) * 1000)  # ms

    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95)]
    p99 = sorted(latencies)[int(len(latencies) * 0.99)]
    avg = statistics.mean(latencies)

    print(f"  HeadObject ({count} calls): avg={avg:.1f}ms  p50={p50:.1f}ms  "
          f"p95={p95:.1f}ms  p99={p99:.1f}ms")
    return {"operation": "HeadObject", "count": count,
            "avg_ms": round(avg, 2), "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2), "p99_ms": round(p99, 2)}


def bench_get_object(keys, count=100):
    """GetObject 지연 측정"""
    import random
    sample = random.sample(keys, min(count, len(keys)))
    latencies = []

    for key in sample:
        start = time.time()
        resp = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        resp["Body"].read()  # 전체 읽기
        latencies.append((time.time() - start) * 1000)

    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95)]
    p99 = sorted(latencies)[int(len(latencies) * 0.99)]
    avg = statistics.mean(latencies)

    print(f"  GetObject ({count} calls): avg={avg:.1f}ms  p50={p50:.1f}ms  "
          f"p95={p95:.1f}ms  p99={p99:.1f}ms")
    return {"operation": "GetObject", "count": count,
            "avg_ms": round(avg, 2), "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2), "p99_ms": round(p99, 2)}


def bench_put_object(count=100, value_size=1024):
    """PutObject 지연 측정"""
    data = b"x" * value_size
    latencies = []

    for i in range(count):
        key = f"bench-put/tmp-{uuid.uuid4().hex}.dat"
        start = time.time()
        s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=data)
        latencies.append((time.time() - start) * 1000)

    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95)]
    p99 = sorted(latencies)[int(len(latencies) * 0.99)]
    avg = statistics.mean(latencies)

    print(f"  PutObject ({count} calls, {value_size}B): avg={avg:.1f}ms  p50={p50:.1f}ms  "
          f"p95={p95:.1f}ms  p99={p99:.1f}ms")
    return {"operation": "PutObject", "count": count, "value_size": value_size,
            "avg_ms": round(avg, 2), "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2), "p99_ms": round(p99, 2)}


def main():
    print("=" * 70)
    print("S3 File Listing & Search Performance Benchmark")
    print(f"Bucket: {BUCKET_NAME}  Region: {REGION}")
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 70)

    all_results = {
        "bucket": BUCKET_NAME,
        "region": REGION,
        "timestamp": datetime.now().isoformat(),
        "experiments": []
    }

    create_bucket()

    try:
        # ============================================================
        # 실험 1: PutObject / GetObject / HeadObject 기본 지연
        # ============================================================
        print("\n--- Experiment 1: Basic I/O Latency ---")
        keys_1k = upload_files(1000, prefix="exp1", value_size=1024)

        exp1 = {
            "name": "Basic I/O Latency (1K files, 1KB each)",
            "head": bench_head_object(keys_1k, 100),
            "get": bench_get_object(keys_1k, 100),
            "put_1kb": bench_put_object(50, 1024),
            "put_10kb": bench_put_object(50, 10240),
            "put_100kb": bench_put_object(50, 102400),
        }
        all_results["experiments"].append(exp1)

        # ============================================================
        # 실험 2: 파일 수에 따른 ListObjectsV2 성능
        # ============================================================
        print("\n--- Experiment 2: ListObjectsV2 by File Count ---")

        # 100 files
        upload_files(100, prefix="list-100", value_size=64)
        r100 = bench_list_all("list-100", "100 files ")

        # 1,000 files (already have from exp1)
        r1k = bench_list_all("exp1", "1K files ")

        # 10,000 files
        keys_10k = upload_files(10000, prefix="list-10k", value_size=64)
        r10k = bench_list_all("list-10k", "10K files ")

        # 50,000 files
        keys_50k = upload_files(50000, prefix="list-50k", value_size=64)
        r50k = bench_list_all("list-50k", "50K files ")

        exp2 = {
            "name": "ListObjectsV2 by File Count",
            "results": [r100, r1k, r10k, r50k]
        }
        all_results["experiments"].append(exp2)

        # ============================================================
        # 실험 3: 프리픽스 필터링 효과 (50K 파일에서)
        # ============================================================
        print("\n--- Experiment 3: Prefix Filtering (50K files) ---")
        r_full = bench_list_all("list-50k", "full scan ")
        r_prefix = bench_list_prefix_filter("list-50k", 5)

        exp3 = {
            "name": "Prefix Filtering Effect (50K files)",
            "full_scan": r_full,
            "prefix_filter": r_prefix
        }
        all_results["experiments"].append(exp3)

        # ============================================================
        # 실험 4: 파일 수 증가에 따른 GetObject 지연 변화
        # ============================================================
        print("\n--- Experiment 4: GetObject Latency vs File Count ---")
        get_1k = bench_get_object(keys_1k, 50)
        get_10k = bench_get_object(keys_10k, 50)
        get_50k = bench_get_object(keys_50k, 50)

        exp4 = {
            "name": "GetObject Latency vs File Count",
            "get_1k_files": get_1k,
            "get_10k_files": get_10k,
            "get_50k_files": get_50k
        }
        all_results["experiments"].append(exp4)

        # ============================================================
        # 결과 요약
        # ============================================================
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)

        print("\n[ListObjectsV2 Performance]")
        print(f"  {'Files':>10}  {'Time (s)':>10}  {'Objects/s':>12}")
        print(f"  {'─'*10}  {'─'*10}  {'─'*12}")
        for r in exp2["results"]:
            print(f"  {r['object_count']:>10,}  {r['avg_s']:>10.3f}  "
                  f"{r['object_count']/r['avg_s']:>12,.0f}")

        print("\n[GetObject Latency vs File Count]")
        print(f"  {'Files':>10}  {'avg (ms)':>10}  {'p50 (ms)':>10}  "
              f"{'p95 (ms)':>10}  {'p99 (ms)':>10}")
        print(f"  {'─'*10}  {'─'*10}  {'─'*10}  {'─'*10}  {'─'*10}")
        for label, r in [("1K", get_1k), ("10K", get_10k), ("50K", get_50k)]:
            print(f"  {label:>10}  {r['avg_ms']:>10.1f}  {r['p50_ms']:>10.1f}  "
                  f"{r['p95_ms']:>10.1f}  {r['p99_ms']:>10.1f}")

        print("\n[PutObject Latency by Value Size]")
        print(f"  {'Size':>10}  {'avg (ms)':>10}  {'p50 (ms)':>10}  "
              f"{'p95 (ms)':>10}  {'p99 (ms)':>10}")
        print(f"  {'─'*10}  {'─'*10}  {'─'*10}  {'─'*10}  {'─'*10}")
        for label, r in [("1KB", exp1["put_1kb"]), ("10KB", exp1["put_10kb"]),
                         ("100KB", exp1["put_100kb"])]:
            print(f"  {label:>10}  {r['avg_ms']:>10.1f}  {r['p50_ms']:>10.1f}  "
                  f"{r['p95_ms']:>10.1f}  {r['p99_ms']:>10.1f}")

        # JSON 저장
        import os
        os.makedirs("output", exist_ok=True)
        output_path = "output/results.json"
        with open(output_path, "w") as f:
            json.dump(all_results, f, indent=2, default=str)
        print(f"\nResults saved to: {output_path}")

    finally:
        delete_bucket()


if __name__ == "__main__":
    main()
