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
lf = boto3.client("lakeformation", region_name=REGION)
iam_client = boto3.client("iam", region_name=REGION)
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


def run_query(sql, database=None, label="", catalog=None):
    """Athena 쿼리 실행 및 시간 측정"""
    params = {
        "QueryString": sql,
        "ResultConfiguration": {
            "OutputLocation": f"s3://{ATHENA_OUTPUT_BUCKET}/results/"
        },
    }
    if database or catalog:
        ctx = {}
        if database:
            ctx["Database"] = database
        if catalog:
            ctx["Catalog"] = catalog
        params["QueryExecutionContext"] = ctx

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


LF_ROLE_NAME = f"s3dd-lf-{RUN_ID}"
CATALOG_NAME = "s3tablescatalog"


def setup_s3_tables():
    """S3 Table Bucket + Namespace + Table + Lake Formation 통합"""
    print("\n--- Setting up S3 Tables + Lake Formation ---")

    table_bucket_arn = f"arn:aws:s3tables:{REGION}:{ACCOUNT_ID}:bucket/{TABLE_BUCKET_NAME}"

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

    # 4. IAM Role for Lake Formation
    print("  Creating Lake Formation IAM role...", end=" ", flush=True)
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lakeformation.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }
    try:
        iam_client.create_role(
            RoleName=LF_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
        )
        # Inline policy for S3 Tables access
        iam_client.put_role_policy(
            RoleName=LF_ROLE_NAME,
            PolicyName="S3TablesAccess",
            PolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetObject*", "s3:ListBucket", "s3:GetBucket*"],
                        "Resource": "*"
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3tables:*"],
                        "Resource": f"{table_bucket_arn}/*"
                    }
                ]
            })
        )
        print("done")
    except iam_client.exceptions.EntityAlreadyExistsException:
        print("already exists")
    except Exception as e:
        print(f"error: {e}")

    # Wait for IAM propagation
    print("  Waiting for IAM propagation (10s)...", end=" ", flush=True)
    time.sleep(10)
    print("done")

    lf_role_arn = f"arn:aws:iam::{ACCOUNT_ID}:role/{LF_ROLE_NAME}"

    # 5. Register resource with Lake Formation (account-level ARN)
    account_tables_arn = f"arn:aws:s3tables:{REGION}:{ACCOUNT_ID}:bucket/*"
    print(f"  Registering with Lake Formation ({account_tables_arn})...", end=" ", flush=True)
    try:
        lf.register_resource(
            ResourceArn=account_tables_arn,
            RoleArn=lf_role_arn,
            WithFederation=True,
        )
        print("done")
    except lf.exceptions.AlreadyExistsException:
        print("already registered")
    except Exception as e:
        print(f"error: {e}")

    # 6. Create Glue federated catalog (s3tablescatalog is account-level global)
    print("  Creating Glue federated catalog...", end=" ", flush=True)
    try:
        glue.create_catalog(
            Name=CATALOG_NAME,
            CatalogInput={
                "FederatedCatalog": {
                    "Identifier": account_tables_arn,
                    "ConnectionName": "aws:s3tables",
                },
                "CreateDatabaseDefaultPermissions": [],
                "CreateTableDefaultPermissions": [],
            }
        )
        print(f"done (catalog: {CATALOG_NAME})")
    except Exception as e:
        err_msg = str(e)
        if "reserved name" in err_msg or "AlreadyExists" in err_msg:
            print("already exists (reserved global catalog)")
        else:
            print(f"error: {e}")

    # 7. Grant permissions to current user on S3 Tables catalog
    print("  Granting Lake Formation permissions...", end=" ", flush=True)
    caller_arn = sts.get_caller_identity()["Arn"]
    try:
        # Grant on the federated catalog's database (namespace)
        lf.grant_permissions(
            Principal={"DataLakePrincipalIdentifier": caller_arn},
            Resource={
                "Database": {
                    "CatalogId": CATALOG_NAME,
                    "Name": NAMESPACE,
                }
            },
            Permissions=["ALL"],
            PermissionsWithGrantOption=["ALL"],
        )
        # Grant on all tables in the namespace
        lf.grant_permissions(
            Principal={"DataLakePrincipalIdentifier": caller_arn},
            Resource={
                "Table": {
                    "CatalogId": CATALOG_NAME,
                    "DatabaseName": NAMESPACE,
                    "TableWildcard": {},
                }
            },
            Permissions=["ALL"],
            PermissionsWithGrantOption=["ALL"],
        )
        print("done")
    except Exception as e:
        print(f"error: {e}")

    # Wait for catalog propagation
    print("  Waiting for catalog propagation (15s)...", end=" ", flush=True)
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


def insert_sample_data(database, table_path, label, row_count=1000, catalog=None):
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
        run_query(insert_sql, database=database, catalog=catalog)

    print(f"done ({row_count} rows)")


def benchmark_queries(database, table_path, label, trials=5, catalog=None):
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
            result = run_query(sql, database=database, label=f"{tag}", catalog=catalog)
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

    # Glue federated catalog (skip if reserved global catalog)
    print("  Deleting Glue federated catalog...", end=" ", flush=True)
    try:
        glue.delete_catalog(CatalogId=CATALOG_NAME)
        print("done")
    except Exception as e:
        print(f"skipped: {e}")

    # Lake Formation resource deregistration
    print("  Deregistering Lake Formation resource...", end=" ", flush=True)
    account_tables_arn = f"arn:aws:s3tables:{REGION}:{ACCOUNT_ID}:bucket/*"
    try:
        lf.deregister_resource(ResourceArn=account_tables_arn)
        print("done")
    except Exception as e:
        print(f"skipped: {e}")

    # Lake Formation IAM role
    print("  Deleting Lake Formation IAM role...", end=" ", flush=True)
    try:
        iam_client.delete_role_policy(RoleName=LF_ROLE_NAME, PolicyName="S3TablesAccess")
        iam_client.delete_role(RoleName=LF_ROLE_NAME)
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
    # Phase 2: S3 Tables (Lake Formation integration done in setup)
    # ============================================================
    tables_ok = setup_s3_tables()
    if tables_ok:
        # Athena에서 S3 Tables 접근: catalog="s3tablescatalog", db=NAMESPACE
        tables_table_path = f'"{NAMESPACE}"."{TABLE_NAME}"'

        print(f"\n  S3 Tables Athena path: {CATALOG_NAME}.{NAMESPACE}.{TABLE_NAME}")

        # 테이블 존재 확인
        print("  Checking table access...", end=" ", flush=True)
        check_result = run_query(
            f"SELECT 1 FROM {tables_table_path} LIMIT 1",
            catalog=CATALOG_NAME,
        )
        if check_result and check_result["state"] == "SUCCEEDED":
            print("accessible!")
            insert_sample_data(None, tables_table_path, "S3 Tables", catalog=CATALOG_NAME)
            tables_results = benchmark_queries(
                None, tables_table_path, "S3 Tables", catalog=CATALOG_NAME,
            )
            all_results["experiments"]["s3_tables"] = tables_results
        else:
            print("not accessible via Athena")
            print("  S3 Tables benchmark skipped — Lake Formation integration may need adjustment.")

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
