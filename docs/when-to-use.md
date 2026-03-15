# When to Use S3 Patterns

## Decision Guide

| 조건 | S3 패턴 사용 | 전용 서비스 사용 |
|------|-------------|----------------|
| 지연 요구 | 100ms+ 허용 | sub-10ms 필수 |
| 트래픽 | 분당 수백~수천 | 분당 수만 이상 |
| 값 크기 | 4KB 이상 | 4KB 이하 |
| 스토리지 | 10GB+ | 소규모 |
| 트랜잭션 | 불필요 | ACID 필수 |
| 관리 부담 | 제로 희망 | 허용 가능 |
| 예산 | 최소화 | 유연 |

## Pattern-Specific Guide

### KV Store: S3 vs DynamoDB
- **S3 선택:** 값 > 4KB, 저빈도 접근, 대규모 스토리지
- **DynamoDB 선택:** 값 <= 4KB + 고빈도, sub-10ms 필수, 트랜잭션 필요

### Event Store: S3 vs Kinesis
- **S3 선택:** 장기 아카이브, 비용 효율, 순서 무관
- **Kinesis 선택:** 실시간 스트리밍, 순서 보장, 고빈도

### Litestream+SQLite: S3+Fargate vs RDS
- **S3+Fargate 선택:** 극저가, 다운타임 허용, 읽기 중심
- **RDS 선택:** 무중단, 동시 쓰기 부하, 멀티 AZ

### Serverless RDBMS: S3+Athena vs Aurora
- **S3+Athena 선택:** 비정기 쿼리 (일 10회 미만), 분석/보고
- **Aurora 선택:** OLTP, 고빈도, 밀리초 응답

### File I/O: S3 vs EBS/EFS
- **S3 선택:** 대용량 순차 I/O, 비용, 동시 접근
- **EBS 선택:** 저지연 랜덤 I/O, POSIX 필수
