# S3 + Athena: Serverless RDBMS 대체 가능성 리서치 보고서

> 리서치 일자: 2026-03-15
> 소스: AWS 공식 문서, AWS 블로그, re:Invent 발표, 벤치마크 자료, G2/Tinybird 비교 분석

---

## 목차

1. [Athena 최신 기능 및 가격 정책](#1-athena-최신-기능-및-가격-정책)
2. [S3 + Athena 아키텍처 패턴](#2-s3--athena-아키텍처-패턴)
3. [성능 특성](#3-성능-특성)
4. [비용 비교 시나리오](#4-비용-비교-시나리오)
5. [한계점 및 우회 방안](#5-한계점-및-우회-방안)
6. [최신 AWS 발표 (2024-2026)](#6-최신-aws-발표-2024-2026)
7. [결론 및 권장 사항](#7-결론-및-권장-사항)

---

## 1. Athena 최신 기능 및 가격 정책

### 1.1 Athena Engine Version 3

- **기반**: Trino/Presto 오픈소스 분산 SQL 엔진
- **지원**: ANSI SQL, 대규모 JOIN, 윈도우 함수, 배열, 복합 타입
- **데이터 포맷**: CSV, JSON, ORC, Avro, Parquet
- **특징**: 클러스터 관리 없이 대용량 데이터셋에 대한 병렬 쿼리 실행
- **ML 통합**: SageMaker 추론을 SQL 쿼리 내에서 직접 호출 가능

> **출처**: [AWS Athena Features](https://aws.amazon.com/athena/features/)

### 1.2 가격 정책 — 더 이상 $5/TB만이 아님

| 과금 모델 | 설명 | 적합 대상 |
|-----------|------|-----------|
| **Per-query (기본)** | 스캔된 데이터 TB당 $5 | 비정기적, 소량 쿼리 |
| **Capacity Reservations (DPU)** | DPU-hour당 $0.44 | 예측 가능한 워크로드, 대시보드 |

- 두 모델을 **동일 계정에서 동시 사용** 가능
- Capacity Reservations으로 최대 **95% 비용 절감** 가능 (짧은 워크로드 기준)
- Parquet, 파티셔닝, 압축을 통해 스캔량 대폭 절감 가능

### 1.3 Athena Provisioned Capacity (Capacity Reservations)

- **개념**: 전용 서버리스 컴퓨트를 DPU 단위로 예약
- **용도**: 우선순위 워크로드, 동시성 제어, 24/7 대시보드
- **최신 업데이트 (2026-02-10)**:
  - **1분 단위 예약** 지원 (기존 더 긴 최소 기간에서 축소)
  - **최소 4 DPU**로 하향
  - 오토스케일링 지원으로 동적 워크로드 대응

> **출처**: [AWS Blog - 1분 예약](https://aws.amazon.com/blogs/big-data/amazon-athena-adds-1-minute-reservations-and-new-capacity-control-features/) (2026-02-10)

### 1.4 ACID 트랜잭션 (Apache Iceberg 통합)

- **Iceberg 테이블**을 S3 + Glue Catalog 기반으로 생성/관리
- **지원 기능**:
  - 스키마 에볼루션
  - 타임 트래블 쿼리
  - 스냅샷 격리(Snapshot Isolation) 기반 트랜잭션 일관성
  - `MERGE INTO`, `UPDATE`, `DELETE` 지원
- **상태**: 프로덕션 레디, 안정적 성숙 단계

### 1.5 Federated Query

- **30개 이상** 데이터 소스에 대한 연합 쿼리 지원
- **주요 소스**: Redshift, DynamoDB, Google BigQuery, Azure Synapse, Redis, Snowflake, SAP HANA
- S3 데이터와 외부 소스를 **데이터 이동 없이** SQL로 조인 가능
- JDBC/ODBC, BI 도구 연동 지원

---

## 2. S3 + Athena 아키텍처 패턴

### 2.1 AWS 공식 권장 패턴

AWS는 Athena를 RDS의 **완전 대체**가 아닌, **분석/Ad-hoc 쿼리용 보완재**로 포지셔닝한다.

**패턴 1: 이벤트 아카이빙**
```
RDS → Lambda + EventBridge → S3 (YYYY/MM/DD 파티션) → Athena 쿼리
```
- RDS의 14일 보존 제한을 넘어선 장기 감사/분석용
- 출처: [AWS Blog - RDS Events 장기 저장](https://aws.amazon.com/blogs/database/long-term-storage-and-analysis-of-amazon-rds-events-with-amazon-s3-and-amazon-athena/)

**패턴 2: 히스토리컬 데이터 오프로딩**
```
RDS PostgreSQL → S3 (CSV/Parquet) → Athena
활성 데이터: RDS에서 직접 조회
과거 데이터: Athena를 통해 S3에서 조회
```
- RDS 쿼리 성능 개선 + 비용 절감
- 출처: [AWS Blog - Historical Data Joining](https://aws.amazon.com/blogs/database/joining-historical-data-between-amazon-athena-and-amazon-rds-for-postgresql/)

**패턴 3: 감사 추적 (Audit Trail)**
```
RDS → AWS DMS → S3 (Parquet, 파티셔닝) → Athena
```
- 페타바이트급 감사 데이터를 비용 효율적으로 관리
- 출처: [AWS Blog - Petabyte Audit Trail](https://aws.amazon.com/blogs/database/turn-petabytes-of-relational-database-records-into-a-cost-efficient-audit-trail-using-amazon-athena-aws-dms-amazon-rds-and-amazon-s3/)

### 2.2 Parquet 최적화 전략

| 전략 | 효과 | 세부사항 |
|------|------|----------|
| **파티셔닝** | 스캔량 50-90% 감소 | `YEAR/MONTH/DAY` 계층적 파티션, 쿼리 시 불필요 파티션 스킵 |
| **칼럼 프루닝** | I/O 대폭 감소 | `SELECT *` 대신 필요 칼럼만 지정 |
| **파일 압축** | 저장 비용 + 스캔 비용 절감 | 아래 비교표 참조 |
| **파일 크기 최적화** | 소규모 파일 문제 방지 | 128MB~1GB 크기로 병합(compaction) |

**압축 알고리즘 비교**:

| 압축 방식 | 압축률 | 해제 속도 | 적합 대상 |
|-----------|--------|-----------|-----------|
| **Snappy** | 보통 | 매우 빠름 | Athena 기본값, 빈번한 쿼리 |
| **Zstd** | 높음 | 빠름 | 대용량 데이터, 저장 비용 최적화 |
| **Gzip** | 최고 | 느림 | 드문 접근, 레이턴시 민감하지 않은 경우 |

---

## 3. 성능 특성

### 3.1 Cold Start 및 쿼리 초기화

- **Cold Start**: 수 초 ~ 30-60초 (임시 컴퓨트 리소스 On-demand 할당)
- 메타데이터 캐시가 있으면 빨라짐, 없으면 느려짐
- **P95 레이턴시**: 공유 인프라 특성상 피크 시 소규모 스캔도 10초 이상 가능

> **출처**: [Tinybird - ClickHouse vs Athena](https://www.tinybird.co/blog/clickhouse-vs-amazon-athena)

### 3.2 데이터 크기별 쿼리 시간 (Parquet 기준, 근사치)

| 스캔 데이터 | 예상 응답 시간 | 비고 |
|-------------|---------------|------|
| **1MB** | < 1초 | 스핀업 오버헤드 최소 |
| **100MB** | 수 초 ~ 10-30초 | |
| **1GB** | 10-60초 | 최적화 수준에 따라 편차 |
| **10GB** | 30초 ~ 수 분 | |
| **100GB** | 30-60초 (최적화 시) ~ 수 분 | Cold run 기준 |

### 3.3 쿼리 복잡도별 성능

| 쿼리 유형 | 성능 | 비고 |
|-----------|------|------|
| `SELECT * LIMIT 10` | 수 초 이내 | 메타데이터 캐시 시 |
| 단순 집계 (COUNT, SUM) | 수 초 ~ 수십 초 | 파티션 프루닝 효과 큼 |
| GROUP BY + 집계 | 10초 ~ 수 분 | 데이터 크기 의존 |
| 복합 JOIN + 집계 | 2-5분+ | 10억 행 조인 시; 파티셔닝 필수 |

### 3.4 Engine V2 → V3 성능 개선

- TPC-DS 3TB 벤치마크 기준 **3배 빠른 실행**, **70% 적은 데이터 스캔**
- 복잡한 TPC-DS 쿼리: 75GB 스캔 실패 → 17GB 스캔, **165초**로 성공

> **출처**: [AWS Blog - Engine V2 벤치마크](https://aws.amazon.com/blogs/big-data/run-queries-3x-faster-with-up-to-70-cost-savings-on-the-latest-amazon-athena-engine/)

### 3.5 Athena vs Aurora Serverless v2 비교

| 항목 | Athena | Aurora Serverless v2 |
|------|--------|---------------------|
| **최적 워크로드** | Ad-hoc 분석, 대용량 스캔 | OLTP + 혼합 분석 |
| **레이턴시** | 초~분 단위 | 밀리초~초 단위 |
| **동시성** | 제한적 (워크그룹 기반) | 높음 |
| **데이터 규모** | 페타바이트급 | 테라바이트급 |
| **인프라** | 완전 서버리스 | 서버리스이나 DB 인스턴스 관리 |

---

## 4. 비용 비교 시나리오

### 4.1 서비스별 월간 비용 비교

> 가정: us-east-1, Parquet 포맷, 30일/월. 쿼리당 스캔량은 최적화 전 기준.

| 시나리오 | 쿼리/일 | 쿼리당 스캔 | **S3+Athena** | **Aurora Serverless v2** | **Redshift Serverless** |
|----------|---------|------------|---------------|--------------------------|------------------------|
| 저빈도-소량 | 10 | 1 TB | **~$1,650** | ~$1,376 | **~$172** |
| 저빈도-대량 | 10 | 10 TB | ~$15,300 | ~$2,876 | **~$346** |
| 중빈도-소량 | 100 | 1 TB | ~$15,400 | ~$3,876 | **~$691** |
| 중빈도-대량 | 100 | 10 TB | ~$150,800 | ~$10,876 | **~$1,728** |
| 고빈도-소량 | 1,000 | 1 TB | ~$151,200 | ~$15,876 | **~$2,102** |
| 고빈도-대량 | 1,000 | 10 TB | ~$1,502,400 | ~$50,876 | **~$4,205** |

**핵심 인사이트**:
- Athena는 스캔량에 **선형 비례**하여 비용 증가 — 고빈도에서 매우 비쌈
- Redshift Serverless가 거의 모든 시나리오에서 **가장 저렴**
- Aurora는 OLTP 혼합 시 유리하지만 순수 분석에는 Redshift가 우위

### 4.2 숨겨진 비용 (S3 + Athena)

| 항목 | 과금 기준 | 월 예상 비용 (예시) |
|------|-----------|-------------------|
| **Glue Data Catalog** | 100 객체당 $1/월 | 1M 객체 = $10,000/월 |
| **S3 GET 요청** | 1,000건당 $0.005 | 1,000 쿼리/일 × 1TB = ~$50/월 |
| **S3 PUT 요청** | 1,000건당 $0.0004 | 결과 저장 = ~$10/월 |
| **쿼리 결과 저장** | $0.023/GB-월 | 100GB 결과/월 = ~$2.30/월 |

> Glue Data Catalog의 파티션/객체 수가 많으면 의외로 큰 비용 발생 가능

### 4.3 손익분기점: Athena vs Aurora Serverless v2

- **쿼리당 1TB 스캔 기준**: 약 **10 쿼리/일**에서 이미 Aurora가 저렴
- **쿼리당 10TB 스캔 기준**: Aurora가 거의 항상 저렴 (데이터가 DB에 이미 로드된 경우)
- **핵심**: Athena가 저렴한 구간은 **매우 비정기적이고 소량인 Ad-hoc 쿼리** 뿐
- **단, Parquet 최적화(파티셔닝, 칼럼 프루닝)로 실제 스캔량을 1/10~1/100로 줄이면 상황이 달라짐**

### 4.4 실질적 비용 최적화 후 재계산

파티셔닝 + 칼럼 프루닝으로 스캔량이 **원래의 10%**로 줄어든다고 가정:

| 시나리오 | 쿼리/일 | 최적화 후 스캔 | **S3+Athena (최적화 후)** |
|----------|---------|---------------|--------------------------|
| 저빈도-소량 | 10 | 100GB/쿼리 | **~$165** |
| 중빈도-소량 | 100 | 100GB/쿼리 | **~$1,540** |
| 고빈도-소량 | 1,000 | 100GB/쿼리 | **~$15,120** |

> 최적화 후에도 고빈도에서는 Redshift Serverless가 우위

---

## 5. 한계점 및 우회 방안

### 5.1 UPDATE/DELETE 불가 (표준 테이블)

- S3는 불변(immutable) 객체 스토리지 → 파일 전체 재작성 필요
- **우회**: Apache Iceberg 테이블 사용
  - `MERGE INTO`, `UPDATE`, `DELETE` 지원
  - 메타데이터 파일을 통한 행 단위 변경 (전체 재작성 불필요)
  - 스냅샷 격리 기반

### 5.2 쿼리 동시성 제한

| 제한 항목 | 값 | 비고 |
|-----------|-----|------|
| 워크그룹당 동시 쿼리 | 기본 5-20개 | 설정 가능, 증가 요청 가능 |
| 쿼리당 DPU | 20-1,000 | 컴퓨트 스케일 제어 |
| 행/칼럼 최대 크기 | 32MB | 하드 리밋 |
| CTAS 파티션 | 최대 100개 | `INSERT INTO`로 우회 |

- **우회**: 다수 워크그룹 분리, 큐잉 활성화, 고동시성 필요 시 Redshift 검토

### 5.3 실시간 수집 불가

- Athena는 S3에 **이미 존재하는** 데이터만 쿼리 가능
- 트리거, CDC, 스트리밍 기본 미지원
- **배치 ETL 패턴 필요**:
  - AWS DMS → S3 (Parquet, 파티셔닝)
  - Glue ETL 잡 (스케줄 기반)
  - Lambda + EventBridge (이벤트 기반)
  - Apache Airflow (복합 워크플로우)

### 5.4 Apache Iceberg가 판도를 바꾸는가?

**개선되는 점**:
- ACID 트랜잭션 (스냅샷 격리)
- `MERGE`/`UPDATE`/`DELETE` 지원
- 타임 트래블 쿼리
- 효율적 파티션 프루닝

**여전히 남는 한계**:
- 서버리스/쿼리 전용 (저장 프로시저, UDF 제한)
- 동시성 제한 변함없음
- 실시간 수집 불가
- OLTP 워크로드에는 여전히 부적합

> **결론**: Iceberg는 S3+Athena를 **분석용 데이터베이스**로 격상시키지만, **OLTP RDBMS 대체는 불가**

### 5.5 트랜잭션 격리 수준

- Iceberg 테이블: **스냅샷 격리(Snapshot Isolation)** 단일 레벨만 지원
- READ COMMITTED, SERIALIZABLE 등 RDBMS 수준의 격리 레벨은 미지원
- RDBMS의 MVCC와는 다른 Iceberg 고유 스냅샷 메커니즘 기반

---

## 6. 최신 AWS 발표 (2024-2026)

### 6.1 re:Invent 2024 (2024년 11-12월)

| 발표 | 내용 | 영향 |
|------|------|------|
| **S3 Tables** | Apache Iceberg 관리형 테이블, "table bucket" 신규 버킷 타입 | 게임 체인저 — 아래 상세 |
| **SageMaker Lakehouse** | Athena를 통한 연합 쿼리 (S3, Redshift, DynamoDB, Snowflake) | 통합 분석 |
| **S3 Queryable Metadata** (Preview) | S3 객체 메타데이터를 Athena/Redshift로 직접 쿼리 | 데이터 거버넌스 |

### 6.2 re:Invent 2025 (2025년 11-12월)

| 발표 | 내용 | 영향 |
|------|------|------|
| **Iceberg 통계 자동 적용** | 쿼리 플래닝에 Iceberg 테이블 통계 자동 활용 | 쿼리 가속 |
| **Athena for Apache Spark** | 인터랙티브 탐색 → 페타바이트급 Spark 잡 확장 | 워크로드 확대 |

### 6.3 2026년 초

| 발표 | 내용 | 영향 |
|------|------|------|
| **1분 Capacity Reservations** (2026-02-10) | 최소 4 DPU, 1분 단위 예약, 오토스케일링 | 비용 유연성 대폭 개선 |

### 6.4 S3 Tables 심층 분석

**S3 Tables**는 이 리서치의 가장 중요한 발견이다.

**개요**:
- 2024년 12월 발표, Preview로 출시 (us-east-1, us-east-2, us-west-2)
- GA 시점은 2026년 3월 기준 미확인
- Apache Iceberg 포맷의 **관리형 테이블** — "table bucket"이라는 새로운 S3 버킷 유형

**일반 S3 + Iceberg vs S3 Tables 비교**:

| 항목 | 일반 S3 + Iceberg | S3 Tables |
|------|-------------------|-----------|
| **관리** | 수동 (compaction, 스냅샷 등 직접 관리) | **완전 관리형** (자동 최적화) |
| **성능** | 기본 성능 | **3배 빠른 쿼리**, **10배 높은 TPS** |
| **접근 제어** | 버킷/객체 레벨 IAM | **테이블 레벨 ARN/정책** |
| **API** | S3 객체 API | **테이블 전용 API** (CreateTable 등) |
| **자동 최적화** | 없음 | Compaction, 스냅샷 관리, 미참조 파일 제거 |

**자동 최적화 상세**:
- **Compaction**: 소규모 Parquet 파일 자동 병합 → S3 요청 감소 → 3배 성능
- **스냅샷 관리**: Iceberg 스냅샷 (타임 트래블) 자동 관리
- **미참조 파일 제거**: 불필요 파일 자동 정리로 스토리지 절감
- **Intelligent-Tiering**: 접근 패턴 기반 자동 계층화

**가격**: 기본 S3 요금 적용 (추가 요금 없음)

**의미**: S3 Tables는 S3+Athena 패턴을 **기본 데이터 레이크**에서 **완전 관리형 분석 데이터베이스 경험**으로 격상시킨다.

---

## 7. 결론 및 권장 사항

### 7.1 S3 + Athena는 RDBMS를 대체할 수 있는가?

| 워크로드 유형 | 대체 가능 여부 | 이유 |
|--------------|---------------|------|
| **Ad-hoc 분석** | O (적합) | 서버리스, 페타바이트급, 비용 효율적 |
| **배치 보고서** | O (적합) | 스케줄 기반 ETL + Athena 조합 |
| **감사/규정 준수** | O (매우 적합) | 장기 저장 + 비정기 쿼리 |
| **대시보드 (BI)** | △ (조건부) | Capacity Reservations 필요, 레이턴시 주의 |
| **OLTP (트랜잭션)** | X (부적합) | 레이턴시, 동시성, UPDATE/DELETE 한계 |
| **실시간 분석** | X (부적합) | 배치 ETL 필수, Cold Start 존재 |

### 7.2 최적 사용 시나리오

```
비정기 분석 쿼리 (일 10회 미만, 소량 스캔)
    → S3 + Athena (Per-query 과금)

예측 가능한 분석 워크로드 (일 100회+)
    → S3 + Athena Capacity Reservations 또는 Redshift Serverless

고빈도 분석 (일 1,000회+)
    → Redshift Serverless (거의 항상 저렴)

OLTP + 분석 혼합
    → Aurora Serverless v2 + Athena (히스토리컬 데이터 오프로딩)
```

### 7.3 S3 Tables가 바꾸는 미래

S3 Tables (2024년 12월 발표)는 이 판도를 근본적으로 변화시킬 잠재력이 있다:
- **수동 관리 제거**: Compaction, 스냅샷, 파일 정리 자동화
- **3배 성능 향상**: 기존 S3+Iceberg 대비
- **추가 비용 없음**: 기본 S3 요금만 적용
- GA 이후 S3+Athena 패턴의 **실질적 진입 장벽이 크게 낮아질 전망**

### 7.4 핵심 수치 요약

| 지표 | 값 |
|------|-----|
| Athena 기본 가격 | $5/TB 스캔 |
| Athena DPU 가격 | $0.44/DPU-hour |
| Cold Start | 수 초 ~ 60초 |
| 1GB Parquet 쿼리 | 10-60초 |
| 동시 쿼리 (기본) | 5-20개/워크그룹 |
| Iceberg MERGE/UPDATE/DELETE | 지원 (스냅샷 격리) |
| S3 Tables 성능 향상 | 3x 쿼리, 10x TPS |
| Athena가 저렴한 구간 | < 10 쿼리/일, 소량 스캔 |

---

## 출처 목록

### AWS 공식
- [AWS Athena Features](https://aws.amazon.com/athena/features/)
- [AWS Athena Release Notes](https://docs.aws.amazon.com/athena/latest/ug/release-notes.html)
- [Athena 1-Minute Reservations (2026-02)](https://aws.amazon.com/blogs/big-data/amazon-athena-adds-1-minute-reservations-and-new-capacity-control-features/)
- [Athena Performance Tuning](https://docs.aws.amazon.com/athena/latest/ug/performance-tuning.html)
- [Athena Service Limits](https://docs.aws.amazon.com/athena/latest/ug/service-limits.html)
- [Athena Limitations](https://docs.aws.amazon.com/athena/latest/ug/other-notable-limitations.html)
- [Redshift Pricing](https://aws.amazon.com/redshift/pricing/)

### AWS 블로그
- [RDS Events 장기 저장 + Athena](https://aws.amazon.com/blogs/database/long-term-storage-and-analysis-of-amazon-rds-events-with-amazon-s3-and-amazon-athena/)
- [Athena + RDS PostgreSQL 히스토리컬 조인](https://aws.amazon.com/blogs/database/joining-historical-data-between-amazon-athena-and-amazon-rds-for-postgresql/)
- [Petabyte Audit Trail](https://aws.amazon.com/blogs/database/turn-petabytes-of-relational-database-records-into-a-cost-efficient-audit-trail-using-amazon-athena-aws-dms-amazon-rds-and-amazon-s3/)
- [Engine V2 3x 성능](https://aws.amazon.com/blogs/big-data/run-queries-3x-faster-with-up-to-70-cost-savings-on-the-latest-amazon-athena-engine/)

### re:Invent 발표
- [re:Invent 2024 Top Announcements](https://aws.amazon.com/blogs/aws/top-announcements-of-aws-reinvent-2024/)
- [re:Invent 2024 Analytics Announcements](https://aws.amazon.com/blogs/big-data/top-analytics-announcements-of-aws-reinvent-2024/)
- [re:Invent 2025 Analytics](https://aws.amazon.com/blogs/big-data/aws-analytics-at-reinvent-2025-unifying-data-ai-and-governance-at-scale/)

### S3 Tables
- [S3 Tables 발표 (2024-12)](https://aws.amazon.com/about-aws/whats-new/2024/12/amazon-s3-tables-apache-iceberg-tables-analytics-workloads/)
- [S3 Tables Features](https://aws.amazon.com/s3/features/tables/)
- [S3 Tables vs Self-Managed Iceberg](https://builder.aws.com/content/39n7WU54TBsV3OlKwtJsnL54PVL/amazon-s3-tables-vs-self-managed-apache-iceberg-on-s3-a-technical-deep-dive-for-startups)

### 비교/벤치마크
- [Tinybird: ClickHouse vs Athena](https://www.tinybird.co/blog/clickhouse-vs-amazon-athena)
- [BryteFlow: Athena vs Redshift Spectrum](https://bryteflow.com/face-off-aws-athena-vs-redshift-spectrum/)
- [Athena vs RDS](https://aws.plainenglish.io/choosing-between-aws-athena-and-aws-rds-34e2117f2b06)
- [Aurora vs Athena](https://aws.plainenglish.io/290-choosing-between-amazon-aurora-and-athena-a-cloud-architects-guide-c3f5c4b2cc0a)
