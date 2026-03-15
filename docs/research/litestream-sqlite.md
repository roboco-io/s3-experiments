# Litestream + SQLite + S3 + Fargate 리서치 보고서

> 작성일: 2025-07-15
> 목적: SQLite를 Fargate에서 운영하고 Litestream으로 S3에 복제하는 아키텍처의 실현 가능성 조사
> 방법: Perplexity AI를 통한 다중 쿼리 리서치 (코드 작성 없음)

---

## 1. Litestream 프로젝트 현황

### 기본 정보
- **GitHub**: https://github.com/benbjohnson/litestream
- **최신 버전**: v0.5.5 (2025년 12월 18일 릴리스)
- **유지보수 상태**: 활발히 유지보수 중. v0.5.6, v0.5.7 이슈가 존재하여 지속 개발 중 확인
- **주요 변경 (v0.5.x)**: 순수 Go 드라이버 `modernc.org/sqlite`로 마이그레이션 (cgo 불필요), Azure SDK v2 업데이트
- **출처**: GitHub releases 페이지, litestream.io (2025년)

### WAL 스트리밍 작동 원리
1. Litestream은 **백그라운드 프로세스**로 실행
2. SQLite API를 통해 데이터베이스에 접근 (파일 직접 읽기 금지 — 손상 방지)
3. WAL 파일의 변경을 모니터링하고, 트랜잭션 커밋 시 **WAL 세그먼트를 실시간으로 스토리지에 스트리밍**
4. 주기적으로 **스냅샷** (전체 데이터베이스 복사본) 생성
5. 스냅샷 + WAL 세그먼트를 별도로 복제하여 효율적인 시점 복구 지원
6. WAL을 로그 스트림처럼 테일링하며, 체크포인트를 투명하게 처리

### RPO (Recovery Point Objective)
- WAL 업로드 빈도에 따라 **일반적으로 1~15초**의 RPO 달성
- 기본 복제는 연속/스트리밍 방식 (고정 간격이 아님)
- `monitor-interval`, `checkpoint-interval` 등 설정 가능
- **출처**: debugg.ai (2025), bluetickconsultants.com (2025)

### RTO (Recovery Time Objective)
- 복원 프로세스: **최신 스냅샷 다운로드 → 이후 WAL 세그먼트 순차 적용**
- RTO는 **데이터베이스 크기와 리플레이 속도에 의존** — 소규모 DB는 수초~수분, 대규모 DB는 수분~수시간
- 특정 시점까지 복원 가능 (point-in-time recovery)

### 지원 스토리지 백엔드

| 백엔드 | 지원 여부 | 비고 |
|--------|----------|------|
| **AWS S3** | O | 네이티브 지원 (`s3://bucket/path.db`) |
| **MinIO** | O | S3 호환 API 사용 |
| **Backblaze B2** | O | S3 호환 API 사용 |
| **DigitalOcean Spaces** | O | S3 호환 API 사용 |
| **Google Cloud Storage** | O | S3 호환 모드(interop) 사용 |
| **Azure Blob Storage** | O | v0.5.0+에서 네이티브 지원 (Azure SDK v2) |

### 알려진 제한사항
- **백업 전용 도구** — 라이브 읽기 복제본이나 다중 쓰기 불가
- 최종 일관성(eventual consistency) 제공, 강한 일관성 미지원
- 단일 인스턴스에서만 안전하게 동작 (다중 인스턴스 동시 쓰기 불가)
- WAL 세그먼트 간 극소량의 데이터 손실 가능성 존재

---

## 2. SQLite in Containers / Fargate

### 컨테이너 환경에서의 SQLite 특성
- **AWS 공식 가이드 부재**: Fargate는 스테이트리스 컨테이너에 초점, SQLite 같은 파일 기반 DB에 대한 공식 아키텍처 없음
- **임시 스토리지**: Fargate 태스크는 20~200 GiB 임시 스토리지 제공, 태스크 재시작 시 데이터 소실
- **WAL 모드**: 컨테이너에서 WAL 파일은 임시 스토리지에 존재하므로, 재시작 시 리셋됨 → **Litestream 없이는 데이터 손실 불가피**

### 싱글 라이터 제한의 실질적 영향
- SQLite는 **무제한 동시 읽기, 단일 쓰기**만 허용
- 수평 확장(다중 태스크)은 쓰기 부하가 높은 앱에서 실패
- Fargate에서 공유 스토리지 미지원 → 각 태스크가 자체 DB 사본 필요, 동기화 복잡
- **적합한 워크로드**: 단일 태스크, 저동시성 앱 (내부 도구, 관리자 패널 등)

### 리소스 요구사항
- SQLite 자체는 경량 (수 MB RAM, 최소 CPU)
- Fargate 태스크 정의: vCPU 0.25~16, 메모리 0.5~120 GiB
- 소규모 SQLite 앱은 **0.25 vCPU, 0.5 GiB RAM**으로 충분
- 임시 스토리지 20~200 GiB가 DB 크기 제한

### 커뮤니티 사례
- NocoDB: Litestream + Fargate + IAM 역할로 S3 백업 구현 (NocoDB 커뮤니티 포스트)
- **출처**: AWS ECS 보안 문서 (2020~), Hacker News (~2023), NocoDB 커뮤니티

---

## 3. Fargate Spot

### 중단(Interruption) 동작
1. AWS가 Spot 용량 회수 시 **SIGTERM 시그널 발송**
2. **2분간의 경고 기간** 제공 — 이 동안 정상 종료 수행
3. 2분 후 태스크 강제 종료
4. EC2 Spot과 달리 중지(stop)나 최대 절전(hibernate) 옵션 없음 — **항상 종료(terminate)**
5. 중단 사유: 용량 회수, 호스트 유지보수, 하드웨어 해제

### 가격 비교 (US East - N. Virginia)

| 리소스 | On-Demand | Spot | 할인율 |
|--------|-----------|------|--------|
| **vCPU** | $0.04048/시간 | $0.01286/시간 | ~68% |
| **메모리 (GB)** | $0.004445/시간 | $0.001412/시간 | ~68% |
| **임시 스토리지** | $0.000111/GB/시간 (20GB 초과분) | 동일 | - |

- 기본 20GB 임시 스토리지 포함
- **초 단위 과금, 최소 1분**
- Spot은 **최대 70% 할인** 광고, 실제 ~68% 할인
- **출처**: aws.amazon.com/fargate/pricing/ (2025)

### 월간 비용 예시 (4 vCPU, 16GB RAM 기준)

| 유형 | 시간당 | 월간 (730시간) |
|------|--------|---------------|
| **On-Demand** | ~$0.233 | ~$170 |
| **Spot** | ~$0.074 | ~$54 |

### 정상 종료 패턴 (Graceful Shutdown)

1. **시그널 핸들링**: SIGTERM 핸들러 등록 → 새 작업 수신 중단 → 진행 중 작업 완료 → 종료
2. **`stopTimeout: 120`**: 태스크 정의에 설정하여 2분 경고 기간 전체 활용
3. **SQS 큐 워커 패턴**: 미확인 메시지는 자동으로 큐로 복귀 — Spot에 가장 자연스러운 패턴
4. **ALB 연동**: 짧은 등록 해제 지연으로 트래픽 빠르게 라우팅 변경
5. **EventBridge**: `SpotInterruption` 이벤트 캡처 → SNS 알림

### 모범 사례
- **On-Demand 베이스 + Spot 혼합**: 최소 가용성은 On-Demand로 보장
- **다중 AZ 분산**: Spot 중단은 AZ별로 발생 가능, 분산으로 위험 감소
- **스테이트리스 유지**: 상태를 DynamoDB, SQS, S3 등 외부 서비스에 저장
- **적합한 워크로드**: 배치 처리, 큐 워커, 개발/스테이징 환경, 스테이트리스 웹 서버, CI/CD
- **부적합한 워크로드**: 싱글톤 태스크, 장시간 DB 연결, 시작에 수시간 걸리는 태스크

### Litestream + Fargate Spot 시 고려사항
- SIGTERM 수신 시 Litestream이 마지막 WAL 세그먼트를 S3에 플러시해야 함
- 2분 경고 시간은 WAL 플러시에 충분
- 복원 시 새 태스크가 S3에서 스냅샷 + WAL 다운로드 후 재개

---

## 4. 대안 및 관련 프로젝트

### 비교표

| 솔루션 | 아키텍처 | 일관성 | 복제 방식 | 유지보수 상태 |
|--------|---------|--------|----------|-------------|
| **Litestream** | 단일 DB 백업 도구 | 시점 복구 (eventual) | WAL → 오브젝트 스토리지 | **활발** (v0.5.5, 2025.12) |
| **LiteFS (Fly.io)** | FUSE 파일시스템, 다중 노드 | 일관성 토큰 기반 | WAL 세그먼트 리더→팔로워 | **개발 우선순위 하락** (Cloud 서비스 2024.10 종료, 프리-1.0 베타) |
| **rqlite** | Raft 합의 기반 분산 클러스터 | 강한 일관성 (Raft) | Raft 로그 복제 | 활발 (추정) |
| **dqlite** | Raft 기반 경량 분산 | 강한 일관성 (Raft) | Raft 합의 | 활발 (추정) |
| **Turso/libSQL** | SQLite 포크 + 클라이언트/서버 | 요청별 조정 가능 | 프라이머리 쓰기 + HTTP/WS 읽기 복제본 | **활발** (관리형 서비스) |
| **Cloudflare D1** | Workers용 관리형 SQLite | 플랫폼 관리 | 리전별 프라이머리 + 내구성 | 활발 (관리형) |

### 핵심 차이점

- **Litestream vs LiteFS**: Litestream은 백업/DR 도구, LiteFS는 라이브 읽기 복제본 제공. LiteFS는 Fly.io 의존성이 높고 2024년 10월 LiteFS Cloud 종료 후 개발 우선순위 하락
- **Litestream vs rqlite/dqlite**: rqlite/dqlite는 다중 쓰기 지원하나 Raft 합의 오버헤드로 지연 시간 증가. Litestream은 단순성 우선
- **Litestream vs Turso**: Turso는 글로벌 에지 읽기(30+ 위치), DB-per-user 멀티테넌트 지원. 관리형이라 운영 부담 적지만 비용 발생
- **출처**: debugg.ai (2025), dev.to (2024~2026 트렌드)

---

## 5. 프로덕션 사용 사례

### 알려진 사용 사례

| 사용자/서비스 | 워크로드 | 스토리지 | 비용 | 출처/날짜 |
|-------------|---------|---------|------|----------|
| **ExtensionPay.com** | 월 ~1.2억 요청 (대부분 캐시) | Backblaze B2 | $0/월 | Hacker News (2024.01.20) |
| **Erik Minkel** | Rails 8 프로덕션 (Kamal 배포) | S3 | 미공개 | erikminkel.com (2025.12.31) |
| **LogSnag "Tiny Stack"** | Astro + SQLite + Litestream | S3 | 미공개 | logsnag.com (날짜 미상) |

### 적합한 워크로드
- **읽기 중심** 단일 노드 앱 (네트워크 지연 없는 빠른 N+1 쿼리)
- 관리형 DB 서버 없이 빠르게 런칭하는 웹 프로덕션
- ML 상태 캡처, 에페머럴 머신의 내구성 있는 샌드박스
- 사전 샤딩된 데이터 (공유 읽기 전용 + 사용자별 파일)
- NVMe 서버의 사이드 프로젝트

### 장애 시나리오 및 데이터 손실 보고
- **보고된 장애/데이터 손실 사례 없음** (조사 범위 내)
- 사용자들은 원활한 복제와 복원 불필요 경험 보고
- crash-safe WAL 처리와 오브젝트 스토리지를 통한 내구성 강조

### 비용 비교 (SQLite + Litestream vs RDS)

| 항목 | SQLite + Litestream | Amazon RDS |
|------|-------------------|------------|
| **스토리지 비용** | $0~수 센트/일 (B2/S3) | 인스턴스 비용 + 스토리지 비용 |
| **설정** | DB 서버 없음, 파일 기반 + 백그라운드 프로세스 | 별도 서버 프로비저닝/관리 필요 |
| **내구성** | WAL → S3 스트리밍, 시점 복원 | 내장 복제본 (추가 비용) |
| **운영** | 자체 모니터링 필요 | 관리형 (자동 백업, 패치) |

- 정량적 RDS 비교 ($/GB, IOPS)는 공개된 자료 없음
- **출처**: Hacker News (2024.01), litestream.io, erikminkel.com (2025.12)

---

## 6. S3 기반 데이터베이스 백업/내구성 계층

### S3 Cross-Region Replication (CRR) for DR
- 프라이머리 S3 버킷에서 다른 리전의 세컨더리 버킷으로 **자동 복제**
- 리전 장애 시 세컨더리 버킷에서 복원 가능
- **버전 관리 활성화 필수** — CRR 규칙 전제 조건
- 메타데이터 (AWS Glue 카탈로그, 권한 등)는 수동 동기화 필요
- 활성-수동(active-passive) 또는 활성-활성(active-active) 구성 가능

### S3 Versioning for Point-in-Time Recovery
- 모든 객체 버전 보존 → 특정 이전 버전으로 복원 가능
- 실수 삭제, 덮어쓰기, 손상으로부터 복구
- CRR/SRR과 결합 시 복제된 백업에도 버전 이력 유지
- Litestream 스냅샷/WAL 세그먼트에 버전 관리 적용 → 이중 안전장치

### S3 Glacier for Long-term Archives
- **라이프사이클 정책으로 자동 전환**: S3 Standard → S3 IA → Glacier (30~90일 후)
- Glacier Flexible Retrieval 또는 Deep Archive로 콜드 스토리지 최적화
- 검색 시간: 분~시간 (Flexible), 12~48시간 (Deep Archive)
- Vault Lock으로 불변성/컴플라이언스 보장
- 정기적 복원 테스트 권장

### S3 스토리지 비용

| 스토리지 클래스 | 비용 (GB/월) | 용도 |
|---------------|-------------|------|
| **S3 Standard** | ~$0.023 | 활성 백업 |
| **S3 IA** | ~$0.0125 | 비활성 백업 |
| **Glacier Flexible** | ~$0.004 | 장기 아카이브 |
| **Glacier Deep Archive** | ~$0.00099 | 초장기 아카이브 |
| **CRR 전송** | ~$0.02/GB | 리전 간 복제 |
| **PUT 요청** | ~$0.005/1,000건 | 쓰기 작업 |

### S3 vs 전통적 백업 비교

| 항목 | S3 기반 | 전통적 (테이프/디스크) |
|------|---------|---------------------|
| **내구성** | 99.999999999% (11 9s) | 단일 사이트, 낮은 중복성 |
| **RTO/RPO** | 준실시간 복제, 버전 관리로 시점 복구 | 수시간~수일, 수동 |
| **확장성** | 무제한, 자동 페일오버 | 하드웨어 제한 |
| **비용** | 사용량 기반, 콜드 티어 저렴 | 높은 CapEx, 지속 유지보수 |

- **출처**: AWS S3 문서, virtualizationreview.com (2025.11), oneuptime.com (2026.01~02)

---

## 7. 종합 평가

### Litestream + SQLite + S3 + Fargate 아키텍처 실현 가능성

**장점:**
- 극도로 낮은 비용 (S3 스토리지 수 센트/일)
- 운영 단순성 (DB 서버 없음, 백그라운드 프로세스 하나)
- 1~15초 RPO로 거의 실시간 백업
- Fargate Spot 활용 시 컴퓨팅 비용 ~68% 절감
- cgo 불필요 (v0.5.x) — 컨테이너 이미지 단순화

**위험 요소:**
- 싱글 라이터 제한으로 수평 확장 불가
- Fargate 임시 스토리지 의존 — 태스크 재시작 시 복원 프로세스 필요
- Fargate Spot 중단 시 2분 이내 WAL 플러시 + 정상 종료 필요
- 대규모 DB의 경우 복원 시간(RTO) 증가
- 공식 AWS 아키텍처/가이드 부재
- Litestream은 활발히 유지보수 중이나, 아직 소규모 프로젝트

**권장 워크로드:**
- 읽기 중심, 단일 인스턴스 앱
- 월간 수억 요청 이하 규모
- 내부 도구, 관리자 패널, SaaS MVP
- 비용 최적화가 우선인 사이드 프로젝트/스타트업

**비권장 워크로드:**
- 높은 쓰기 동시성 필요
- 수평 확장 필수
- 강한 일관성 보장 필요 (→ rqlite, dqlite 고려)
- 글로벌 에지 읽기 필요 (→ Turso 고려)
- 엄격한 SLA/가용성 요구 (→ RDS/Aurora 고려)
