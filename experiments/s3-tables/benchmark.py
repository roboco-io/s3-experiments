"""
S3 Tables + Athena 벤치마크
- S3 Table Bucket 생성 → Iceberg 테이블 → 데이터 삽입
- Athena를 통한 Cold Start / Warm 쿼리 지연 측정
- 일반 S3 + Athena Iceberg 테이블과 비교
- 완료 후 모든 리소스 자동 삭제
"""

import boto3
import json
import time
import uuid
import statistics
import os
from datetime import datetime

REGION = "us-east-1"
RUN_ID = uuid.uuid4().hex[:8]
TABLE_BUCKET_NAME = f"s3dd-tables-{RUN_ID}"
REGULAR_BUCKET_NAME = f"s3dd-regular-{RUN_ID}"
ATHENA_OUTPUT_BUCKET = f"s3dd-athena-out-{RUN_ID}"
NAMESPACE = "benchmark"
TABLE_NAME = "orders"
WORKGROUP = "primary"
DATABASE_NAME = f"s3dd_bench_{RUN_ID.replace('-', '_')}"

s3 = boto3.client("s3", region_name=REGION)
s3tables = boto3.client("s3tables", region_name=REGION)
athena = boto3.client("athena", region_name=REGION)
glue = boto3.client("glue", region_name=REGION)
sts = boto3.client("sts", region_name=REGION)

ACCOUNT_ID = sts.get_caller_identity()["Account"]


def wait_query(query_id):
    """Athena 쿼리 완료 대기 후 결과 반환"""
    while True:
        resp = athena.get_query_execution(QueryExecutionId=query_id)
        state = resp["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return resp["QueryExecution"]
        time.sleep(1)


def run_query(sql, database=None, label=""):
    """Athena 쿼리 실행 및 시간 측정"""
    params = {
        "QueryString": sql,
        "ResultConfiguration": {
            "OutputLocation": f"s3://{ATHENA_OUTPUT_BUCKET}/results/"
        },
    }
    if database:
        params["QueryExecutionContext"] = {"Database": database}

    start = time.time()
    resp = athena.start_query_execution(**params)
    query_id = resp["QueryExecutionId"]
    execution = wait_query(query_id)
    total_ms = (time.time() - start) * 1000

    state = execution["Status"]["State"]
    stats = execution.get("Statistics", {})
    engine_ms = stats.get("EngineExecutionTimeInMillis", 0)
    queue_ms = stats.get("QueryQueueTimeInMillis", 0)
    planning_ms = stats.get("QueryPlanningTimeInMillis", 0)
    scanned_bytes = stats.get("DataScannedInBytes", 0)

    if state == "FAILED":
        reason = execution["Status"].get("StateChangeReason", "unknown")
        print(f"    FAILED: {reason}")
        return None

    result = {
        "label": label,
        "state": state,
        "total_ms": round(total_ms),
        "engine_ms": engine_ms,
        "queue_ms": queue_ms,
        "planning_ms": planning_ms,
        "scanned_bytes": scanned_bytes,
        "scanned_mb": round(scanned_bytes / 1024 / 1024, 2),
    }

    if label:
        print(f"    {label}: total={total_ms:.0f}ms  engine={engine_ms}ms  "
              f"queue={queue_ms}ms  plan={planning_ms}ms  scanned={result['scanned_mb']}MB")

    return result


def setup_athena_output():
    """Athena 결과 저장용 버킷 생성"""
    print("  Creating Athena output bucket...", end=" ", flush=True)
    s3.create_bucket(Bucket=ATHENA_OUTPUT_BUCKET)
    print("done")


def setup_s3_tables():
    """S3 Table Bucket + Namespace + Table 생성"""
    print("\n--- Setting up S3 Tables ---")

    # 1. Table Bucket 생성
    print("  Creating table bucket...", end=" ", flush=True)
    try:
        s3tables.create_table_bucket(name=TABLE_BUCKET_NAME)
        print("done")
    except Exception as e:
        print(f"error: {e}")
        return False

    # 2. Namespace 생성
    print("  Creating namespace...", end=" ", flush=True)
    table_bucket_arn = f"arn:aws:s3tables:{REGION}:{ACCOUNT_ID}:bucket/{TABLE_BUCKET_NAME}"
    try:
        s3tables.create_namespace(
            tableBucketARN=table_bucket_arn,
            namespace=[NAMESPACE]
        )
        print("done")
    except Exception as e:
        print(f"error: {e}")

    # 3. Iceberg Table 생성
    print("  Creating Iceberg table...", end=" ", flush=True)
    try:
        s3tables.create_table(
            tableBucketARN=table_bucket_arn,
            namespace=NAMESPACE,
            name=TABLE_NAME,
            format="ICEBERG",
        )
        print("done")
    except Exception as e:
        print(f"error: {e}")
        return False

    # 4. Glue에서 테이블이 보이도록 카탈로그 통합 대기
    print("  Waiting for Glue catalog integration (15s)...", end=" ", flush=True)
    time.sleep(15)
    print("done")

    return True


def setup_regular_s3_iceberg():
    """일반 S3 + Glue + Athena Iceberg 테이블 설정"""
    print("\n--- Setting up Regular S3 + Iceberg ---")

    # 1. 일반 버킷 생성
    print("  Creating regular bucket...", end=" ", flush=True)
    s3.create_bucket(Bucket=REGULAR_BUCKET_NAME)
    print("done")

    # 2. Glue Database 생성
    print("  Creating Glue database...", end=" ", flush=True)
    try:
        glue.create_database(
            DatabaseInput={
                "Name": DATABASE_NAME,
                "Description": "S3 Tables benchmark - regular Iceberg"
            }
        )
        print("done")
    except Exception as e:
        print(f"error: {e}")

    # 3. Athena로 Iceberg 테이블 생성
    print("  Creating Iceberg table via Athena...", end=" ", flush=True)
    create_sql = f"""
    CREATE TABLE {DATABASE_NAME}.orders (
        order_id STRING,
        customer_id STRING,
        product STRING,
        quantity INT,
        price DOUBLE,
        order_date STRING
    )
    LOCATION 's3://{REGULAR_BUCKET_NAME}/iceberg/orders/'
    TBLPROPERTIES ('table_type' = 'ICEBERG')
    """
    result = run_query(create_sql)
    if result and result["state"] == "SUCCEEDED":
        print("done")
    else:
        print("failed")
        return False

    return True


def insert_sample_data(database, table_path, label, row_count=1000):
    """Athena INSERT로 샘플 데이터 삽입"""
    print(f"  Inserting {row_count} rows into {label}...", end=" ", flush=True)

    # 배치로 삽입 (Athena INSERT INTO ... VALUES)
    batch_size = 200
    for batch_start in range(0, row_count, batch_size):
        batch_end = min(batch_start + batch_size, row_count)
        values = []
        for i in range(batch_start, batch_end):
            values.append(
                f"('ord-{i:06d}', 'cust-{i % 100:04d}', "
                f"'product-{i % 50}', {(i % 10) + 1}, "
                f"{round(9.99 + (i % 100) * 0.5, 2)}, "
                f"'2026-03-{(i % 28) + 1:02d}')"
            )

        insert_sql = f"INSERT INTO {table_path} VALUES {', '.join(values)}"
        run_query(insert_sql, database=database)

    print(f"done ({row_count} rows)")


def benchmark_queries(database, table_path, label, trials=5):
    """Cold start + warm 쿼리 벤치마크"""
    print(f"\n  === Benchmarking: {label} ===")

    queries = [
        ("COUNT(*)", f"SELECT COUNT(*) FROM {table_path}"),
        ("WHERE filter", f"SELECT * FROM {table_path} WHERE customer_id = 'cust-0042' LIMIT 10"),
        ("GROUP BY agg", f"SELECT product, SUM(quantity), AVG(price) FROM {table_path} GROUP BY product"),
        ("ORDER BY", f"SELECT * FROM {table_path} ORDER BY price DESC LIMIT 20"),
    ]

    all_results = []

    for q_label, sql in queries:
        print(f"\n    [{q_label}]")
        timings = []
        for trial in range(trials):
            tag = "COLD" if trial == 0 else f"warm-{trial}"
            result = run_query(sql, database=database, label=f"{tag}")
            if result:
                timings.append(result)
            if trial == 0:
                time.sleep(2)  # cold start 후 잠시 대기

        if timings:
            totals = [t["total_ms"] for t in timings]
            engines = [t["engine_ms"] for t in timings]
            cold = timings[0]["total_ms"]
            warm_totals = totals[1:] if len(totals) > 1 else totals

            summary = {
                "query": q_label,
                "cold_total_ms": cold,
                "cold_engine_ms": timings[0]["engine_ms"],
                "warm_avg_total_ms": round(statistics.mean(warm_totals)),
                "warm_p50_total_ms": round(statistics.median(warm_totals)),
                "warm_avg_engine_ms": round(statistics.mean(engines[1:])) if len(engines) > 1 else engines[0],
                "scanned_mb": timings[0]["scanned_mb"],
                "trials": timings,
            }
            all_results.append(summary)

            print(f"    Summary: cold={cold}ms  warm_avg={summary['warm_avg_total_ms']}ms  "
                  f"warm_p50={summary['warm_p50_total_ms']}ms")

    return all_results


def teardown():
    """모든 리소스 삭제"""
    print("\n=== Tearing down ===")

    # Athena output bucket
    print("  Deleting Athena output...", end=" ", flush=True)
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=ATHENA_OUTPUT_BUCKET):
            if "Contents" in page:
                s3.delete_objects(Bucket=ATHENA_OUTPUT_BUCKET,
                                Delete={"Objects": [{"Key": o["Key"]} for o in page["Contents"]]})
        s3.delete_bucket(Bucket=ATHENA_OUTPUT_BUCKET)
        print("done")
    except Exception as e:
        print(f"error: {e}")

    # Regular S3 bucket
    print("  Deleting regular bucket...", end=" ", flush=True)
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=REGULAR_BUCKET_NAME):
            if "Contents" in page:
                s3.delete_objects(Bucket=REGULAR_BUCKET_NAME,
                                Delete={"Objects": [{"Key": o["Key"]} for o in page["Contents"]]})
        s3.delete_bucket(Bucket=REGULAR_BUCKET_NAME)
        print("done")
    except Exception as e:
        print(f"error: {e}")

    # Glue database + table
    print("  Deleting Glue database...", end=" ", flush=True)
    try:
        glue.delete_table(DatabaseName=DATABASE_NAME, Name="orders")
    except Exception:
        pass
    try:
        glue.delete_database(Name=DATABASE_NAME)
        print("done")
    except Exception as e:
        print(f"error: {e}")

    # Glue catalog for S3 Tables
    print("  Deleting Glue S3 Tables catalog...", end=" ", flush=True)
    try:
        glue.delete_catalog(Name=f"s3tablescatalog/{TABLE_BUCKET_NAME}")
        print("done")
    except Exception as e:
        print(f"error: {e}")

    # S3 Table Bucket
    print("  Deleting S3 table bucket...", end=" ", flush=True)
    table_bucket_arn = f"arn:aws:s3tables:{REGION}:{ACCOUNT_ID}:bucket/{TABLE_BUCKET_NAME}"
    try:
        s3tables.delete_table(
            tableBucketARN=table_bucket_arn,
            namespace=NAMESPACE,
            name=TABLE_NAME
        )
    except Exception:
        pass
    try:
        s3tables.delete_namespace(
            tableBucketARN=table_bucket_arn,
            namespace=NAMESPACE
        )
    except Exception:
        pass
    try:
        s3tables.delete_table_bucket(tableBucketARN=table_bucket_arn)
        print("done")
    except Exception as e:
        print(f"error: {e}")


def main():
    print("=" * 70)
    print("S3 Tables vs Regular S3+Iceberg — Athena Query Benchmark")
    print(f"  Cold start, warm queries, query complexity comparison")
    print(f"  Run ID: {RUN_ID}  Region: {REGION}")
    print(f"  Time: {datetime.now().isoformat()}")
    print("=" * 70)

    all_results = {
        "run_id": RUN_ID,
        "region": REGION,
        "timestamp": datetime.now().isoformat(),
        "experiments": {}
    }

    setup_athena_output()

    # ============================================================
    # Phase 1: Regular S3 + Iceberg + Athena
    # ============================================================
    regular_ok = setup_regular_s3_iceberg()
    if regular_ok:
        insert_sample_data(DATABASE_NAME, f"{DATABASE_NAME}.orders", "regular Iceberg")
        regular_results = benchmark_queries(DATABASE_NAME, f"{DATABASE_NAME}.orders", "Regular S3 + Iceberg")
        all_results["experiments"]["regular_iceberg"] = regular_results

    # ============================================================
    # Phase 2: S3 Tables
    # ============================================================
    tables_ok = setup_s3_tables()
    if tables_ok:
        # S3 Tables 카탈로그 통합: Glue에 카탈로그 등록
        # 카탈로그 이름 형식: s3tablescatalog/<table-bucket-name>
        table_bucket_arn = f"arn:aws:s3tables:{REGION}:{ACCOUNT_ID}:bucket/{TABLE_BUCKET_NAME}"
        s3tables_catalog = f"s3tablescatalog/{TABLE_BUCKET_NAME}"

        print(f"\n  Registering S3 Tables catalog in Glue...", end=" ", flush=True)
        try:
            glue.create_catalog(
                Name=s3tables_catalog,
                CatalogInput={
                    "Description": "S3 Tables benchmark catalog",
                    "FederatedCatalog": {
                        "Identifier": table_bucket_arn,
                    },
                    "CatalogProperties": {
                        "DataLakeAccessProperties": {
                            "DataLakeAccess": True,
                        }
                    },
                }
            )
            print(f"done (catalog: {s3tables_catalog})")
        except glue.exceptions.AlreadyExistsException:
            print("already exists")
        except Exception as e:
            print(f"error: {e}")
            # Try alternative: the catalog may auto-register
            print("  Trying auto-registered catalog name...", end=" ", flush=True)
            try:
                catalogs = athena.list_data_catalogs()
                catalog_names = [c["CatalogName"] for c in catalogs.get("DataCatalogsSummary", [])]
                print(f"available: {catalog_names}")
                for name in catalog_names:
                    if TABLE_BUCKET_NAME in name or "s3tablescatalog" in name.lower():
                        s3tables_catalog = name
                        break
            except Exception as e2:
                print(f"error: {e2}")

        # Athena에서 S3 Tables 테이블 생성 (Iceberg, LOCATION 없이)
        print("  Waiting for catalog propagation (10s)...", end=" ", flush=True)
        time.sleep(10)
        print("done")

        # S3 Tables Iceberg 테이블에 Athena로 데이터 삽입
        # 카탈로그 경로: "s3tablescatalog/<bucket>"."<namespace>"."<table>"
        tables_db = f'"{s3tables_catalog}"."{NAMESPACE}"'
        tables_table_path = f'"{s3tables_catalog}"."{NAMESPACE}"."{TABLE_NAME}"'

        print(f"  S3 Tables path: {tables_table_path}")

        # 테이블 존재 확인
        print("  Checking table access...", end=" ", flush=True)
        check_result = run_query(f"SELECT 1 FROM {tables_table_path} LIMIT 1")
        if check_result and check_result["state"] == "SUCCEEDED":
            print("accessible")
            insert_sample_data(None, tables_table_path, "S3 Tables")
            tables_results = benchmark_queries(None, tables_table_path, "S3 Tables")
            all_results["experiments"]["s3_tables"] = tables_results
        elif check_result and check_result["state"] == "FAILED":
            print("not accessible via Athena")
            print("  Note: S3 Tables requires Lake Formation integration.")
            print("  Attempting CREATE TABLE in S3 Tables catalog...")

            # S3 Tables에서는 CREATE TABLE 시 LOCATION 불필요
            create_sql = f"""
            CREATE TABLE {tables_table_path} (
                order_id STRING,
                customer_id STRING,
                product STRING,
                quantity INT,
                price DOUBLE,
                order_date STRING
            )
            TBLPROPERTIES ('table_type' = 'ICEBERG')
            """
            create_result = run_query(create_sql, label="CREATE TABLE in S3 Tables")
            if create_result and create_result["state"] == "SUCCEEDED":
                insert_sample_data(None, tables_table_path, "S3 Tables")
                tables_results = benchmark_queries(None, tables_table_path, "S3 Tables")
                all_results["experiments"]["s3_tables"] = tables_results
            else:
                print("  S3 Tables benchmark skipped — catalog integration failed.")
                print("  This may require manual Lake Formation setup.")

    # ============================================================
    # Summary
    # ============================================================
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    for exp_name, results in all_results["experiments"].items():
        print(f"\n  [{exp_name}]")
        print(f"  {'Query':<20} {'Cold (ms)':>10} {'Warm avg':>10} {'Warm p50':>10} {'Scanned':>10}")
        print(f"  {'─'*20} {'─'*10} {'─'*10} {'─'*10} {'─'*10}")
        for r in results:
            print(f"  {r['query']:<20} {r['cold_total_ms']:>10} {r['warm_avg_total_ms']:>10} "
                  f"{r['warm_p50_total_ms']:>10} {r['scanned_mb']:>9}MB")

    # 비교
    if "regular_iceberg" in all_results["experiments"] and "s3_tables" in all_results["experiments"]:
        print("\n  [Comparison: S3 Tables vs Regular Iceberg]")
        reg = {r["query"]: r for r in all_results["experiments"]["regular_iceberg"]}
        tab = {r["query"]: r for r in all_results["experiments"]["s3_tables"]}
        for q in reg:
            if q in tab:
                speedup = reg[q]["warm_avg_total_ms"] / max(1, tab[q]["warm_avg_total_ms"])
                cold_speedup = reg[q]["cold_total_ms"] / max(1, tab[q]["cold_total_ms"])
                print(f"  {q:<20}  cold: {cold_speedup:.1f}x  warm: {speedup:.1f}x")

    # 결과 저장
    os.makedirs("output", exist_ok=True)
    with open("output/results.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to output/results.json")

    teardown()


if __name__ == "__main__":
    main()
