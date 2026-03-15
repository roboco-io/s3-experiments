# S3 Deep Dive — 리서치 종합 보고서

**조사 일자:** 2026-03-15
**조사 방법:** Perplexity AI를 통한 AWS 공식 문서, 블로그, 벤치마크, 커뮤니티 사례 조사
**쿼리 횟수:** 약 60회 (6개 병렬 에이전트 × 8~15회 쿼리)

---

## 1. 기존 5개 패턴 조사 결과 요약

### 패턴 1: S3 Key-Value Store

| 항목 | 조사 결과 |
|------|----------|
| **핵심 발견** | "S3가 항상 더 싸다"는 **틀렸다** — DynamoDB 요청 비용이 S3 GET보다 37.5% 저렴 |
| **S3 비용 우위** | 스토리지(DynamoDB 대비 10.9배 저렴)와 대용량 값(4KB 초과 시 DynamoDB RRU 급증) |
| **성능** | S3 Standard 10~200ms vs DynamoDB 3~4ms (25배 차이) |
| **게임 체인저** | 2024.08 Conditional Writes (`If-None-Match`) + 2024.11 (`If-Match` ETag) → CAS 패턴 가능 |
| **Strong Consistency** | 2020.12부터 S3도 strong consistency (이전 최대 장벽 해소) |
| **리서치 갭 = 기회** | S3 vs DynamoDB 직접 벤치마크 (p50/p95/p99) **공개 자료 없음** |
| **Express One Zone** | 2025.04 가격 인하 (GET 85%, PUT 55%) — 고빈도 KV에서 경쟁력 확보 |

**PRD 수정 필요사항:**
- "비용 효율성"을 스토리지 비용 + 대용량 값 관점으로 재프레이밍
- Conditional Writes (2024) 활용을 구현에 포함
- S3 Express One Zone을 KV Store 변형으로 테스트 추가

**상세 보고서:** [kv-store.md](./kv-store.md)

---

### 패턴 2: S3 as Event Store

| 항목 | 조사 결과 |
|------|----------|
| **핵심 발견** | S3는 primary event store로 **부적합** — Kinesis가 이벤트당 45배 저렴 |
| **비용** | S3 PUT + SQS: $5.40/M 이벤트 vs Kinesis on-demand: $0.12/M 이벤트 |
| **S3 가치** | 장기 저장 ($0.023/GB/월)과 11 nines 내구성 — **event data lake / cold archive** |
| **알림 한계** | At-least-once, 순서 미보장, 지연 수초~1분+, 3,000 이벤트/초 초과 시 스로틀링 |
| **실사례** | Zalando: 일 6,000만 이벤트를 S3에 저장 → SQS → Lambda → SNS 팬아웃 |
| **권장 아키텍처** | Hot path (Kinesis) + Cold path (S3 + Object Lock) 하이브리드 |

**PRD 수정 필요사항:**
- "Event Store"에서 "Event Archive / Data Lake" 관점으로 리프레이밍
- Kinesis와의 비용 비교에서 S3의 열세를 정직하게 반영
- Hot+Cold 하이브리드 아키텍처를 PoC에 포함
- S3 Object Lock (WORM) 규제 준수 각도 추가

**상세 보고서:** [event-sourcing.md](./event-sourcing.md)

---

### 패턴 3: Litestream + SQLite + Fargate

| 항목 | 조사 결과 |
|------|----------|
| **Litestream 상태** | v0.5.5 (2025.12.18), 활발히 유지보수, 순수 Go (cgo 불필요) |
| **RPO** | 1~15초 (WAL 스트리밍 간격) |
| **RTO** | DB 크기에 비례 — 소규모 DB는 수 초 |
| **Fargate Spot** | SIGTERM + 2분 경고, On-Demand 대비 ~68% 할인 |
| **프로덕션 사례** | ExtensionPay.com: 월 1.2억 요청, $0/월 (B2 사용). 데이터 손실 보고 없음 |
| **대안** | LiteFS (Fly.io 종속, 2024.10 Cloud 종료 후 하향), rqlite/dqlite (Raft 오버헤드), Turso (관리형) |
| **Rails 8** | Litestream을 Kamal+Rails 8 프로덕션 스택으로 사용하는 사례 증가 |

**PRD 수정 필요사항:**
- RPO 1~15초 범위를 실험 설계에 반영
- Fargate Spot 2분 경고 활용 전략 구체화
- 비교 대상에 Turso/LiteFS 언급 추가

**상세 보고서:** [litestream-sqlite.md](./litestream-sqlite.md)

---

### 패턴 4: S3 + Athena Serverless RDBMS

| 항목 | 조사 결과 |
|------|----------|
| **핵심 발견** | Athena는 더 이상 $5/TB 단일 모델이 아님 — Capacity Reservations (2026.02) 추가 |
| **비용** | 일 100회+ 쿼리 시 Redshift Serverless가 거의 항상 저렴. Athena 유리 구간: 일 10회 미만 ad-hoc |
| **S3 Tables** | 2024.12 re:Invent 발표 — Apache Iceberg 관리형, 기존 대비 **3x 쿼리, 10x TPS** |
| **성능** | Cold Start 수초~60초, 1GB Parquet 쿼리 10~60초, 복합 JOIN 2~5분+ |
| **핵심 최적화** | 파티셔닝 + 컬럼 프루닝으로 스캔량 1/10~1/100 감소 → 비용/성능 모두 개선 |
| **OLTP 부적합** | UPDATE/DELETE 없음 (Iceberg 제외), 동시성 제한, 실시간 수집 불가 |

**PRD 수정 필요사항:**
- "수 초 응답" → 실제로는 **수 초 ~ 수십 초** (cold start 포함)로 현실적 조정
- S3 Tables (Iceberg) 패턴을 변형 실험으로 추가
- Capacity Reservations 비용 모델 반영
- 적합 사용 사례를 "일 10회 미만 ad-hoc 쿼리"로 좁힘

**상세 보고서:** [athena-rdbms.md](./athena-rdbms.md)

---

### 패턴 5: S3 as File I/O

| 항목 | 조사 결과 |
|------|----------|
| **성능** | EBS gp3: 서브ms, 최대 80,000 IOPS. S3 Standard: 100~200ms. S3 Express: 한 자릿수 ms |
| **S3 강점** | 병렬화 기반 집계 처리량 1,800+ MB/s, 비용 ($2.70/100GB vs EBS $8 vs EFS $30) |
| **S3 약점** | append 미지원 (전체 재작성 필요), 파일 락 없음, POSIX 비호환 |
| **최신 기능** | S3 Express One Zone 디렉토리 버킷에서 append 지원 (2025) |
| **Conditional Writes** | 2024.08 If-None-Match, 2024.11 If-Match — 동시성 제어 가능 |
| **비용 역전점** | S3 요청이 EBS보다 비싸지려면 GB당 월 1.4억 GET 필요 — 비현실적 |

**PRD 수정 필요사항:**
- 하이브리드 아키텍처 (Hot→EBS, Shared→EFS, Warm/Cold→S3) 관점 추가
- S3 Express One Zone append 지원을 실험에 포함
- EBS gp3 2025.09 확장 스펙 반영

**상세 보고서:** [file-io.md](./file-io.md)

---

## 2. 신규 패턴 발굴 결과

### Top 3 추천 신규 패턴

#### 1위: S3 Conditional Writes 분산 락 (점수 36/40)

| 항목 | 상세 |
|------|------|
| **기능** | 2024.08 `If-None-Match` + 2024.11 `If-Match` (ETag) → compare-and-swap |
| **대체 대상** | DynamoDB conditional writes 기반 분산 락 |
| **참신성** | 9/10 — 2024년 신기능, 커뮤니티에서 매우 활발히 논의 |
| **실용성** | 9/10 — DynamoDB 없이 분산 락/리더 선출 가능 |
| **벤치마크** | S3 CAS vs DynamoDB 조건부 쓰기 지연/비용 비교 |
| **주요 출처** | morling.dev (2024.08), quanttype.net (2025.02), simonwillison.net (2024.11) |
| **제약** | 펜싱 토큰 미지원, 이중 자릿수 ms 레이턴시 |

#### 2위: S3 Vectors 벡터 검색 (점수 36/40)

| 항목 | 상세 |
|------|------|
| **기능** | 2025.07 프리뷰, 2025.12 GA — S3 네이티브 벡터 저장/검색 |
| **대체 대상** | Pinecone, pgvector, OpenSearch kNN |
| **참신성** | 10/10 — 가장 최신 S3 기능, 거의 알려지지 않음 |
| **실용성** | 8/10 — RAG 파이프라인, 시맨틱 검색에 직접 활용 |
| **벤치마크** | S3 Vectors vs pgvector 쿼리 지연/비용/정확도 비교 |
| **스펙** | 인덱스당 20억 벡터, 웜 쿼리 ~100ms, 전용 벡터 DB 대비 최대 90% 비용 절감 |

#### 3위: S3 as Container Registry (점수 35/40)

| 항목 | 상세 |
|------|------|
| **기능** | S3 버킷을 HTTP로 노출하여 OCI 이미지 레지스트리로 활용 |
| **대체 대상** | ECR, Docker Hub |
| **참신성** | 9/10 — HN에서 큰 화제, 의외성 최고 |
| **실용성** | 8/10 — 커스텀 툴링 필요하지만 비용 절감 명확 |
| **벤치마크** | push/pull 속도 + 비용 비교 vs ECR |
| **출처** | ochagavia.nl (2024), HN discussion (2024.07) |

### 차점자

| 패턴 | 점수 | 비고 |
|------|------|------|
| S3 Tables (Iceberg 관리형) | 34/40 | 2024.12 발표, 기존 Athena 패턴의 진화형으로 통합 가능 |
| S3 Object Lambda | 30/40 | 동적 콘텐츠 변환 — 독립 패턴보다는 다른 패턴의 보조 기능 |
| DuckDB + S3 | 30/40 | Athena 패턴과 중복도 높음 |

---

## 3. 리서치 기반 패턴 재구성 제안

### 조사 결과 반영한 수정 사항

| 패턴 | 변경 전 | 변경 후 (리서치 반영) |
|------|---------|---------------------|
| KV Store | S3가 항상 저렴 | S3는 **스토리지 + 대용량 값**에서 우위. 요청 비용은 DynamoDB가 저렴. Conditional Writes (2024) 활용 |
| Event Store | S3가 Kinesis 대체 | S3는 **cold archive / event data lake** 역할. Hot path는 Kinesis. 하이브리드 아키텍처 |
| Litestream | (변경 없음) | RPO 1~15초, Fargate Spot 68% 할인 확인. 실험 설계 유효 |
| Serverless RDBMS | 수 초 응답 | **수 초 ~ 수십 초** (cold start 포함). S3 Tables (Iceberg) 변형 추가. 적합: 일 10회 미만 |
| File I/O | FS 대체 가능성 | 대용량 순차 I/O에서 강점. 소규모 랜덤 I/O는 EBS가 압도적. 하이브리드 권장 |

### 신규 패턴 추가 제안

기존 5개 패턴에 아래 1~2개 추가를 제안합니다:

**강력 추천: S3 Conditional Writes 분산 락**
- 이유: KV Store 패턴과 시너지 (같은 2024 Conditional Writes 기능 활용)
- KV Store의 "변형 실험"으로 통합하거나 독립 패턴으로 분리 가능
- 벤치마크가 명확하고 커뮤니티 관심이 매우 높음

**선택 추천: S3 Vectors**
- 이유: 가장 최신 (2025.12 GA), AI/RAG 트렌드와 맞물림
- 단, 아직 GA 초기라 CDK 지원이 불안정할 수 있음
- 커뮤니티 임팩트는 가장 클 수 있음

---

## 4. 출처 날짜 분포

| 연도 | 주요 변화 |
|------|----------|
| 2020.12 | S3 Strong Consistency |
| 2023.11 | S3 Express One Zone 출시 |
| 2024.08 | S3 Conditional Writes (If-None-Match) |
| 2024.11 | S3 Conditional Writes (If-Match, ETag) |
| 2024.12 | S3 Tables (Apache Iceberg) 발표 at re:Invent |
| 2025.04 | S3 Express One Zone 가격 인하 (GET 85%, PUT 55%) |
| 2025.07 | S3 Vectors 프리뷰 |
| 2025.09 | EBS gp3 확장 (80K IOPS, 2,000 MB/s) |
| 2025.12 | S3 Vectors GA, Litestream v0.5.5 |
| 2026.02 | Athena Capacity Reservations |

---

## 5. 리서치 파일 인덱스

| 파일 | 주제 | 크기 |
|------|------|------|
| [kv-store.md](./kv-store.md) | S3 Key-Value Store | 19KB |
| [event-sourcing.md](./event-sourcing.md) | S3 Event Sourcing | 14KB |
| [litestream-sqlite.md](./litestream-sqlite.md) | Litestream + SQLite + Fargate | 13KB |
| [athena-rdbms.md](./athena-rdbms.md) | S3 + Athena Serverless RDBMS | 19KB |
| [file-io.md](./file-io.md) | S3 API vs Filesystem I/O | 12KB |
