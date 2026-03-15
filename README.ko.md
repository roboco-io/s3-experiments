# S3 Experiments — S3로 또 뭘 할 수 있을까?

[English](./README.md) | **한국어** | [日本語](./README.ja.md)

> S3가 단순한 저장소가 아니라면? S3를 **Key-Value Store**, **Event Store**, **내구성 RDBMS (Litestream+SQLite)**, **서버리스 RDBMS (Athena)**, **파일 I/O 대안**으로 활용하는 방법을 탐구합니다 — 동작하는 코드, CDK 배포, 전용 AWS 서비스와의 정직한 벤치마크와 함께.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-blue.svg)](https://www.typescriptlang.org/)
[![AWS CDK](https://img.shields.io/badge/AWS_CDK-v2-orange.svg)](https://aws.amazon.com/cdk/)

## 왜 S3인가?

Amazon S3는 흔히 "파일을 넣어두는 곳" 정도로 인식됩니다. 하지만 **GB당 $0.023의 스토리지 비용**, **11 nines(99.999999999%)의 내구성**, **관리할 서버 제로**, **무한한 확장성**을 갖춘 S3는 AWS에서 가장 강력한 기본 요소 중 하나입니다.

이 프로젝트는 S3를 전통적인 역할 너머로 밀어붙이면 어떤 일이 벌어지는지 탐구합니다:

| 얻는 것 | 비용 |
|---------|------|
| 프로비저닝된 용량 제로 | 사용한 만큼만 지불 |
| 서버, 클러스터, 패치 없음 | IAM 정책 = 전체 보안 설정 |
| 어떤 부하에도 자동 스케일링 | 용량 계획 불필요 |
| 99.999999999% 내구성 | 편히 잠들 수 있음 |

**이 프로젝트는 S3가 전용 서비스를 대체한다고 주장하지 않습니다.** 각 패턴에는 S3가 적합한 경우와 DynamoDB, RDS, Aurora를 사용해야 하는 경우를 보여주는 정직한 트레이드오프 분석이 포함되어 있습니다.

## 패턴

| # | 패턴 | 대체 대상 | 핵심 인사이트 | 상태 |
|---|------|----------|-------------|------|
| 1 | [**Key-Value Store**](./patterns/kv-store/) | DynamoDB | S3 객체 키 = 당신의 키, 객체 바디 = 당신의 값. 50만 키를 비용 효율적으로 처리할 수 있을까? | 🔲 |
| 2 | [**S3 as Event Store**](./patterns/event-sourcing/) | Kinesis / SQS | S3 Event Notifications를 내구성 있는 리플레이 가능한 이벤트 로그로 활용. | 🔲 |
| 3 | [**Litestream + SQLite**](./patterns/litestream-sqlite/) | RDS (소규모) | 인메모리 DB 속도 + [Litestream](https://github.com/benbjohnson/litestream)을 통한 S3 내구성. Fargate Spot RTO/RPO 실험. | 🔲 |
| 4 | [**Serverless RDBMS**](./patterns/serverless-rdbms/) | RDS / Aurora | S3의 Parquet + Athena = 데이터베이스 서버 없이 SQL 쿼리. 수 초를 허용할 수 있다면, 왜 RDS에 비용을 쓸까? | 🔲 |
| 5 | [**S3 as File I/O**](./patterns/s3-file-io/) | EBS / EFS | S3 API의 읽기/쓰기는 로컬 파일시스템과 비교해 어떨까? 파일 크기별 성능 프로파일링. | 🔲 |

각 패턴은 **독립적으로 배포 가능**합니다 — 관심 있는 패턴 하나를 골라 10분 이내에 배포하세요.

## 빠른 시작

### 사전 요구사항

- Node.js 20+
- AWS CLI (자격 증명 설정 완료)
- AWS CDK v2 (`npm install -g aws-cdk`)

### 패턴 배포하기

```bash
# 레포 클론
git clone https://github.com/roboco-io/s3-experiments.git
cd s3-experiments

# 의존성 설치
npm install

# 패턴 선택 후 배포
cd patterns/kv-store
npx cdk deploy

# 데모 실행
npx tsx src/demo.ts

# 벤치마크 실행
npm run benchmark

# 정리 (모든 리소스 제거)
npx cdk destroy
```

## 프로젝트 구조

```
s3-experiments/
├── README.md                          # 영어 README
├── README.ko.md                       # 한국어 README (현재 문서)
├── README.ja.md                       # 일본어 README
├── patterns/
│   ├── kv-store/                      # 패턴 1: S3 Key-Value Store
│   │   ├── README.md                  #   아키텍처, 사용법, 트레이드오프
│   │   ├── lib/                       #   CDK 스택
│   │   ├── src/                       #   데모 코드 & Lambda 핸들러
│   │   └── benchmark/                 #   성능 & 비용 비교
│   ├── event-sourcing/                # 패턴 2: S3 Event Store
│   ├── litestream-sqlite/             # 패턴 3: Litestream + SQLite + Fargate
│   ├── serverless-rdbms/             # 패턴 4: S3 + Athena RDBMS
│   └── s3-file-io/                    # 패턴 5: S3 API vs 파일시스템
├── shared/                            # 공통 유틸리티 (S3 클라이언트, 비용 계산기)
├── docs/
│   ├── architecture.md                # 아키텍처 철학
│   ├── cost-comparison.md             # 통합 비용 비교
│   └── when-to-use.md                 # 의사결정 가이드
└── CONTRIBUTING.md                    # 새 패턴 추가 방법
```

## 벤치마크

모든 패턴에는 S3 기반 구현과 대체 대상 전용 AWS 서비스를 비교하는 벤치마크가 포함됩니다.

| 패턴 | 측정 지표 | 비교 대상 |
|------|----------|----------|
| KV Store | 지연시간 (p50/p95/p99), 처리량, 비용/1M 연산 (10K~500K 키) | DynamoDB on-demand (실측) |
| Event Store | 쓰기 지연, 프로젝션 딜레이, 비용/1M 이벤트 | Kinesis Data Streams (공식 가격) |
| Litestream+SQLite | RTO, RPO, 쿼리 지연, 월 비용 (On-Demand vs Spot) | RDS db.t4g.micro (실측) |
| Serverless RDBMS | 복잡도별 쿼리 지연 (1MB~10GB), 스캔 비용, 비용/1K 쿼리 | Aurora Serverless v2 (공식 가격) |
| S3 File I/O | 파일 크기별 읽기/쓰기 지연 (1KB~1GB), 처리량 (MB/s), 동시 IOPS | EBS gp3 + EFS (실측) |

**방법론:** 메트릭당 100회 이상 반복, 처음 10회는 워밍업으로 제외, Lambda cold/warm 지연 분리 보고. 모든 벤치마크는 `us-east-1`에서 실행. 각 패턴의 `benchmark/results.md`에서 상세 확인.

## S3 패턴을 사용할 때

S3 기반 패턴이 빛나는 경우:
- **비용 민감** — 가능한 한 가장 낮은 가격의 스토리지/컴퓨팅이 필요할 때
- **저~중 트래픽** — 분당 수백~수천 요청 (수백만이 아닌)
- **단순함** — 관리할 인프라가 제로이길 원할 때
- **내구성 > 지연시간** — 아카이브, 감사 로그, 이벤트 히스토리

전용 서비스를 사용해야 하는 경우:
- **서브밀리초 지연** — DynamoDB, ElastiCache는 이를 위해 만들어짐
- **복잡한 트랜잭션** — 여러 연산에 걸친 ACID 보장
- **고빈도 읽기** — S3는 프리픽스당 요청 제한이 있음
- **실시간 스트리밍** — Kinesis/SQS가 더 나은 보장을 제공

상세 가이드는 [docs/when-to-use.md](./docs/when-to-use.md)를 참조하세요.

## 기술 스택

- **런타임:** Node.js 20+ / TypeScript 5+
- **IaC:** AWS CDK v2
- **AWS SDK:** @aws-sdk/* v3
- **테스트:** Vitest
- **패키지 매니저:** npm workspaces

## 기여하기

기여를 환영합니다! [CONTRIBUTING.md](./CONTRIBUTING.md)에서 다음 방법을 확인하세요:
- 새로운 S3 패턴 추가
- 기존 벤치마크 개선
- 문서 수정

## 라이선스

MIT License. [LICENSE](./LICENSE)를 참조하세요.

---

**관리할 필요가 없는 인프라가 최고의 인프라다**라는 신념으로 만들어졌습니다.
