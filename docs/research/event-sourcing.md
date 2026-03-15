# S3 Event Store / Event Sourcing 심층 리서치 보고서

> 조사일: 2025-07-17
> 출처: AWS 공식 문서, AWS 블로그, 벤치마크 자료, 커뮤니티 사례 (Perplexity AI 기반 검색)

---

## 1. AWS S3 Event Notifications 공식 기능

### 1.1 지원 이벤트 타입

| 카테고리 | 이벤트 타입 | 설명 |
|----------|------------|------|
| **Object Created** | `s3:ObjectCreated:*`, `Put`, `Post`, `Copy`, `CompleteMultipartUpload` | 객체 생성 시 트리거 (멀티파트 포함) |
| **Object Removed** | `s3:ObjectRemoved:*`, `Delete`, `DeleteMarkerCreated` | 삭제 또는 삭제 마커 생성 |
| **Object Restore** | `s3:ObjectRestore:*` | Glacier 복원 이벤트 |
| **Replication** | `s3:Replication:*` | 교차 리전/동일 리전 복제 이벤트 |
| **Lifecycle** | `s3:LifecycleExpiration:*`, `s3:LifecycleTransition:*` | 수명 주기 전환/만료 |
| **Intelligent-Tiering** | `s3:IntelligentTiering:*` | 계층 이동 이벤트 |
| **기타** | `s3:ObjectTagging:*`, `s3:ObjectAcl:Put`, `s3:ObjectLost:*` | 태그/ACL 변경, RRS 데이터 손실 |

- 알림 설정 시 prefix/suffix 필터링 지원
- 버킷당 최대 **100개** 알림 설정 가능

### 1.2 전달 보장

| 항목 | 세부 내용 |
|------|----------|
| **전달 보장** | **At-least-once** (최소 1회) — 중복 전달 가능 |
| **순서 보장** | **없음** — 동일 객체에 대한 이벤트도 순서 뒤바뀔 수 있음 |
| **내구성** | 재시도는 하지만, 대상이 장기 거부 시 유실 가능성 존재 |
| **SLA** | AWS가 공식 레이턴시 SLA를 제공하지 않음 |

### 1.3 전달 레이턴시

- AWS 공식 문서: "보통 수 초 내, 때로 **1분 이상** 걸릴 수 있음" (출처: AWS S3 Event Notifications 문서)
- AWS 블로그 실측: S3 → Lambda 호출까지 **1초 미만**, 이미지 감지 + 태그 워크플로우 전체 1.3초 (출처: AWS Storage Blog, "Reliable event processing with Amazon S3 event notifications")
- S3 Express One Zone: 개별 라운드트립 ~5ms (표준 S3 대비 10배 빠름)
- 표준 S3 p99 tail latency: **100ms+**

### 1.4 통합 대상

| 대상 | 특징 |
|------|------|
| **AWS Lambda** | 직접 호출, 서버리스 처리. 콜드 스타트 고려 필요 |
| **Amazon SQS** | 내구성 있는 버퍼링, 재시도/DLQ 지원 |
| **Amazon SNS** | 팬아웃 (이메일, 다른 큐/Lambda 등 다중 구독자) |
| **Amazon EventBridge** | 200+ AWS 서비스 연동, 고급 필터링/라우팅 |

- 알림 설정 1개당 **하나의 대상만** 지정 가능 (ARN 기반)
- 페이로드: JSON (버킷명, 객체 키, 이벤트 시간, ETag, 이벤트 타입 포함)

### 1.5 2024-2025 업데이트

- 2024-2025년 S3 Event Notifications의 핵심 기능에 대한 **주요 변경사항 없음**
- EventBridge 통합은 기존 그대로 유지
- S3 Express One Zone (2023 말 출시)이 저지연 사용 사례에 대한 대안으로 자리잡음

---

## 2. Event Sourcing 패턴과 S3

### 2.1 AWS 공식 권장 아키텍처

AWS Prescriptive Guidance (출처: `docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/event-sourcing.html`)에 따르면:

- **Primary Event Store (Hot)**: **Kinesis Data Streams** 권장 — 고처리량, 샤딩, 실시간 스트리밍, 이벤트 리플레이 지원
- **Secondary (DynamoDB)**: DynamoDB Streams는 DynamoDB 테이블 변경 캡처용으로 적합하지만, 보존 기간 24시간 기본값으로 제한적
- **Archive (Cold)**: **S3를 아카이브 저장소**로 권장 — 비용 효율적, 무한 확장

> **핵심 패턴: Hot + Cold 하이브리드**
> Kinesis/DynamoDB (최근 이벤트, 저지연 리플레이) → S3 (장기 보관, 스냅샷 기반 복구)

### 2.2 서비스 간 비교

| 서비스 | 이벤트 소싱 강점 | 한계 |
|--------|----------------|------|
| **Kinesis Data Streams** | 고처리량 쓰기/읽기, 샤딩, 실시간 스트리밍, 리플레이 | 샤드 관리 필요, 비용이 처리량에 비례 |
| **DynamoDB Streams** | 항목 수준 변경 캡처, Lambda 통합 | 보존 24시간, Kinesis보다 낮은 처리량 |
| **S3** | 비용 효율적 불변 저장, 무한 확장 | 높은 읽기 지연, 스트리밍/순서 보장 없음, 배치 지향 |
| **EventBridge** | 서버리스 이벤트 버스, 라우팅/디커플링 | 이벤트 저장소가 아닌 **라우터** 역할 |
| **MSK (Managed Kafka)** | Kafka 호환, 높은 처리량, 장기 보존 | 운영 복잡도 높음 |

### 2.3 EventBridge Pipes + S3

- S3는 EventBridge Pipes의 **지원 이벤트 소스** (출처: AWS EventBridge Pipes 문서)
- `PutObject`, `CopyObject`, `CompleteMultipartUpload` 이벤트 트리거 가능
- 필터링 → 옵션 강화(enrichment) → 대상 전달 (예: Step Functions)
- 전용 통합 코드 없이 포인트-투-포인트 연결 가능

### 2.4 S3를 Primary Event Store로 쓰지 않는 이유

1. **네이티브 스트리밍 없음** — 객체 저장소 특성상 append-only 스트림 미지원
2. **순서 보장 없음** — 이벤트 순서가 보장되지 않아 event sourcing의 핵심 요구사항 미충족
3. **트랜잭션 미지원** — 낙관적 동시성 제어(optimistic concurrency) 불가
4. **서브밀리초 지연 불가** — 표준 S3 PutObject 50-200ms

---

## 3. S3를 Append-Only 이벤트 로그로 사용

### 3.1 S3 Object Versioning → 이벤트 히스토리

- 버전 관리 활성화 시 동일 키에 대한 모든 업로드가 **고유 VersionId**로 저장
- 삭제 시 Delete Marker만 생성 → 이전 버전 접근 가능
- `GET Object --version-id`로 특정 시점 이벤트 조회
- `list-object-versions`로 히스토리 추적

**주의사항:**
- 비현재(noncurrent) 버전이 스토리지 비용 증가 → 수명 주기 정책으로 90일 후 만료 설정 권장
- 빈번한 append 시 버전 수가 **100배** 이상 증가할 수 있음
- 활성화 후 전파까지 **15분** 소요 가능

### 3.2 S3 Object Lock → 불변 이벤트 로그 (WORM)

| 모드 | 특징 |
|------|------|
| **Governance** | 특수 API 헤더로 우회 가능 |
| **Compliance** | 어떤 방법으로도 삭제/수정 불가 — 규제 준수용 |

- SEC Rule 17a-4, 금융 감사 로그 등 규정 준수에 적합
- Legal Hold: 무기한 보존 설정 가능
- **패턴**: 새 버전 업로드 즉시 Lock → 변조 방지 체인 구성

### 3.3 S3 Inventory → 이벤트 리플레이

- CSV/Parquet 형식으로 버킷 내 모든 객체/버전 목록 생성 (일/주 단위)
- `VersionId`, `IsLatest`, `LastModified`, `Size` 포함
- **Athena 연동**: `SELECT * FROM inventory WHERE key LIKE 'events/%' ORDER BY last_modified_date`
- `ListObjectVersions` API 호출 없이 페타바이트 규모 버전 목록 조회 가능

### 3.4 S3 Batch Operations → 이벤트 재처리

- Inventory CSV를 매니페스트로 사용하여 수백만 객체에 대한 벌크 작업 실행
- `RestoreObject`, `CopyObject` 등 지원
- **비용**: 작업당 $0.25 + 객체당 수수료
- **사용 사례**: 1년치 이벤트 히스토리에서 분석 데이터 백필

---

## 4. 성능 및 비용 분석

### 4.1 S3 PutObject 지연 시간

| 티어 | p50 지연 | p90 지연 | p99 지연 |
|------|---------|---------|---------|
| **Standard S3** | 16-26ms | 38-42ms | 100ms+ |
| **S3 Express One Zone** | 2-8ms | - | ~50ms (5-10 라운드트립) |

- 512KB 미만 소형 객체 기준 (출처: AWS S3 Performance Optimization 문서, Tigris 벤치마크)

### 4.2 이벤트 알림 전달 지연

- 일반적: **수 초 내** 전달
- 실측: S3 → Lambda **1초 미만** (AWS Storage Blog)
- 최악의 경우: **1분 이상** (AWS 공식 문서 언급)
- SQS 중간 버퍼 사용 시 추가 지연 발생

### 4.3 비용 비교 (100만 이벤트당, 1KB 이벤트 기준)

| 아키텍처 | 비용 계산 | **100만 이벤트당 비용** |
|----------|----------|----------------------|
| **S3 PUT + SQS** | S3 PUT: $5.00 + SQS: $0.40 | **$5.40** |
| **Kinesis Data Streams (on-demand)** | Ingestion: $0.08/GB + PUT units: $0.04/M | **$0.12** |
| **SQS Standard** | $0.40/M requests | **$0.40** |

> **참고**: S3 PUT 비용은 $0.005/1,000 requests = **$5.00/1M requests** (us-east-1 기준)

### 4.4 비용 손익 분기점

**Kinesis가 모든 볼륨에서 S3+SQS보다 저렴** (1KB 이벤트 기준):
- S3+SQS: $5.40/M 이벤트
- Kinesis on-demand: $0.12/M 이벤트
- **Kinesis가 약 45배 저렴**

단, S3의 가치는 비용이 아닌 **내구성(11 nines)과 장기 저장**에 있음.

**하이브리드 전략이 최적**:
- Hot path: Kinesis → 실시간 처리 ($0.12/M)
- Cold storage: S3 → 장기 보관 (S3 Standard ~$0.023/GB/월, Glacier ~$0.004/GB/월)

### 4.5 비용 요약 표

| 서비스 | 쓰기 비용 | 저장 비용 | 읽기/처리 비용 | 적합한 사용 사례 |
|--------|----------|----------|--------------|----------------|
| S3 Standard | $5.00/M PUT | $0.023/GB/월 | $0.0004/GET | 아카이브, 배치 리플레이 |
| Kinesis (on-demand) | $0.12/M | 포함 (7일) | 소비자당 별도 | 실시간 스트리밍 |
| SQS | $0.40/M | 포함 (14일) | $0.40/M | 작업 큐, 디커플링 |
| DynamoDB | $1.25/M WCU | $0.25/GB/월 | $0.25/M RCU | CRUD + 스트림 |

---

## 5. 실제 사례 및 한계

### 5.1 실제 사용 사례: Zalando

**가장 문서화된 사례** (출처: AWS Storage Blog, ~2020-2022)

- **규모**: 일 6,000만 이벤트, 4,200 Nakadi 이벤트 타입 (위시리스트, 검색 쿼리 등)
- **아키텍처**: S3에 Raw JSON 저장 → S3 Event Notifications → SQS → Lambda → SNS → 1,000+ 큐로 팬아웃
- **최적화**: Parquet 변환으로 분석 효율화 (추천, 수요 예측)
- **비용 절감**: S3 List API 호출 회피로 연 $10,000+ 절감
- **핵심 교훈**: S3를 "이벤트 저장소"가 아닌 **"이벤트 데이터 레이크"**로 활용

### 5.2 AWS 공식 샘플

- AWS Samples (`aws-samples.github.io/eda-on-aws/patterns/event-sourcing/`): DynamoDB를 이벤트 스토어로 권장 (partition key: `streamId`, sort key: `eventNumber`)
- S3는 ETL 파이프라인의 이벤트 트리거 용도로만 사용

### 5.3 알려진 한계

| 한계 | 상세 설명 | 완화 전략 |
|------|----------|----------|
| **순서 미보장** | 동시 PUT 시 알림 순서 뒤바뀜 | `sequencer` 필드 사용, DynamoDB로 순서 추적 |
| **중복 전달** | At-least-once → 중복 가능 | 멱등성(idempotency) 구현, `sequencer` 기반 중복 제거 |
| **팬아웃 제한** | 버킷당 100개 알림 설정 | SNS/EventBridge로 팬아웃 확장 |
| **스로틀링** | 버킷당 3,000+ 이벤트/초 시 알림 스로틀링 | EventBridge/SNS로 분산 |
| **알림 유실** | 일시적 장애 시 드물게 유실 가능 | S3 Inventory 주기적 스캔으로 보완 (Zalando 방식) |
| **리전 제한** | 알림은 동일 리전 내에서만 전달 | 교차 리전 복제 + 대상 리전 알림 설정 |
| **트랜잭션 없음** | 낙관적 동시성 제어 불가 | DynamoDB 조건부 쓰기와 조합 |

### 5.4 이벤트 키 설계 Best Practice

**권장 패턴:**
```
s3://{bucket}/{aggregate-type}/{aggregate-id}/{yyyy}/{mm}/{dd}/{hh}/{timestamp}-{sequence}-{event-type}.json
```

**예시:**
```
s3://events-bucket/order/ord-123/2024/03/15/07/1710489600-001-OrderCreated.json
s3://events-bucket/order/ord-123/2024/03/15/07/1710489601-002-OrderConfirmed.json
```

**설계 원칙:**
1. **Prefix 기반 파티셔닝**: `events/orders/*` → 특정 SQS로 라우팅
2. **Hot partition 회피**: prefix당 5,000 객체/초 제한 → aggregate-id로 분산
3. **시간 기반 파티셔닝**: Spark/Presto/Athena 쿼리 최적화
4. **메타데이터 활용**: `sequencer`, `eventNumber`를 객체 메타데이터에 포함
5. **대규모 버킷**: 4,000+ 이벤트 타입 시 S3 Inventory 매니페스트 활용 (Zalando 사례)

---

## 6. 실측 벤치마크 결과 (2026-03-15)

> 실제 AWS us-east-1 환경에서 S3 → Lambda → DynamoDB 파이프라인으로 측정.
> 실험 코드: [experiments/event-notification/](../../experiments/event-notification/)

### 6.1 전달 보장 (Delivery Guarantee)

| 실험 | 발송 | 수신 | 유실 | 중복 | 동시성 |
|------|------|------|------|------|--------|
| 순차 | 100 | 100 | **0** | **0** | 1 |
| 중규모 | 500 | 500 | **0** | **0** | 10 |
| 대규모 | 2,000 | 2,000 | **0** | **0** | 50 |

**결론:** 2,600개 이벤트에서 유실/중복 **0건**. AWS 문서상 "at-least-once"이지만, 실측에서는 exactly-once에 가깝게 동작. 단, 프로덕션에서는 중복 방지를 위한 멱등성 구현은 여전히 권장.

### 6.2 순서 보장 (Ordering) — 핵심 발견

| 실험 | 순서 역전 수 | 역전률 | sequencer로 복원 가능? |
|------|------------|--------|---------------------|
| 100 순차 | 15 / 99 | **15.2%** | **YES** (역전 0) |
| 500 병렬10 | 211 / 499 | **42.3%** | **NO** (29 역전) |
| 2,000 병렬50 | 978 / 1,999 | **48.9%** | **NO** (355 역전) |

**핵심 발견:**
1. **순차 전송에서도 15% 순서 역전** — S3 Event Notifications는 순서를 전혀 보장하지 않음
2. **동시성 증가 시 역전률 ~50% 수렴** — 거의 랜덤 순서로 도착
3. **sequencer 필드는 순차 전송 시에만 유효** — 동시 쓰기가 있으면 sequencer로도 원래 순서 복원 불가
4. **이벤트 소싱 패턴에서 순서가 중요하다면 S3 Event Notifications는 부적합** — Kinesis Data Streams 또는 DynamoDB Streams 사용 필요

### 6.3 지연시간 (S3 PUT → Lambda 수신)

| 지표 | 100 순차 | 500 병렬10 | 2,000 병렬50 |
|------|---------|-----------|-------------|
| min | 869ms | 862ms | 841ms |
| **avg** | **1,372ms** | **1,309ms** | **1,361ms** |
| **p50** | **1,352ms** | **1,305ms** | **1,354ms** |
| p95 | 1,791ms | 1,639ms | 1,720ms |
| p99 | 2,430ms | 1,710ms | 1,949ms |
| max | 2,430ms | 1,803ms | 2,430ms |

**결론:**
- 일관되게 **p50 ~1.35초** — 부하(100→2,000)와 무관하게 안정적
- AWS 문서의 "수 초 내" 설명과 일치, "1분 이상"은 관측되지 않음
- 최소 지연이 ~840ms이므로 **서브초(sub-second) 처리는 불가능**

### 6.4 실측 기반 S3 Event Store 적합성 판단

```
실측 확인된 사실:
  ✅ 전달률 100% (2,600 이벤트에서 유실/중복 0)
  ✅ 지연시간 안정적 (~1.35초, 부하 무관)
  ❌ 순서 보장 없음 (순차 전송에서도 15% 역전)
  ❌ sequencer로도 동시 쓰기 시 순서 복원 불가
  ❌ 서브초 처리 불가능 (최소 ~840ms)

적합한 사용 사례:
  ✅ 순서 무관한 이벤트 아카이브 (감사 로그, 데이터 레이크)
  ✅ 멱등성 보장된 비동기 처리 (이미지 리사이징, ETL)
  ✅ 장기 보관 + 배치 리플레이

부적합한 사용 사례:
  ❌ 순서 의존적 이벤트 소싱 (CQRS)
  ❌ 실시간 스트림 처리 (< 1초 요구)
  ❌ 정확히 한번(exactly-once) 보장 필수 시스템
```

---

## 7. 결론 및 아키텍처 권장사항

### S3는 Event Store로 적합한가?

| 질문 | 답변 |
|------|------|
| S3를 Primary Event Store로 사용 가능한가? | **권장하지 않음** — 순서 보장/트랜잭션/저지연 부재 |
| S3를 Cold Event Store (아카이브)로 사용 가능한가? | **매우 적합** — 11 nines 내구성, 무한 확장, 저비용 |
| S3 Event Notifications로 이벤트 드리븐 처리가 가능한가? | **가능하지만 제약 있음** — at-least-once, 순서 미보장, 레이턴시 불확실 |

### 권장 아키텍처

```
[Producer] → [Kinesis Data Streams] → [Lambda/Consumer] → [DynamoDB (상태)]
                    ↓
              [Kinesis Firehose]
                    ↓
              [S3 (장기 보관)]  → [Athena (분석)]
                    ↓               → [S3 Batch Ops (재처리)]
              [S3 Object Lock]      → [S3 Inventory (감사)]
              (WORM 규제 준수)
```

- **실시간 처리**: Kinesis Data Streams (Hot path)
- **장기 보관**: S3 Standard/Glacier (Cold path)
- **규제 준수**: S3 Object Lock (Compliance mode)
- **분석/리플레이**: Athena + S3 Inventory
- **이벤트 라우팅**: EventBridge (서비스 간 디커플링)

---

## 참고 자료

| 출처 | URL | 날짜 |
|------|-----|------|
| AWS S3 Event Notifications 문서 | docs.aws.amazon.com/AmazonS3/latest/userguide/EventNotifications.html | 상시 업데이트 |
| AWS Prescriptive Guidance - Event Sourcing | docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/event-sourcing.html | 2024 |
| AWS Storage Blog - Zalando 사례 | aws.amazon.com/blogs/storage/zalando-handles-millions-of-objects-with-amazon-s3-event-notifications/ | ~2020-2022 |
| AWS Storage Blog - Reliable event processing | aws.amazon.com/blogs/storage/reliable-event-processing-with-amazon-s3-event-notifications/ | 2023 |
| AWS Blog - Event ordering and duplicates | aws.amazon.com/blogs/storage/manage-event-ordering-and-duplicate-events-with-amazon-s3-event-notifications/ | 2023 |
| AWS EventBridge Pipes 문서 | docs.aws.amazon.com/eventbridge/latest/userguide/eb-pipes.html | 상시 업데이트 |
| AWS S3 Performance Optimization | docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance.html | 상시 업데이트 |
| Tigris 벤치마크 - Small Objects | tigrisdata.com/blog/benchmark-small-objects/ | 2024 |
| AWS Samples - EDA Patterns | aws-samples.github.io/eda-on-aws/patterns/event-sourcing/ | 2024 |
| EventBridge Pipes Architectural Patterns | aws.amazon.com/blogs/compute/implementing-architectural-patterns-with-amazon-eventbridge-pipes/ | 2023 |
