# S3 Files vs Mountpoint vs EFS — Cold-Cache Benchmark

> 실측일: 2026-05-04 | 리전: us-east-1c | 인스턴스: c6gn.xlarge Spot (ARM/Graviton2, AL2023)
>
> 스펙: [`docs/superpowers/specs/2026-05-04-s3-files-benchmark-design.md`](../superpowers/specs/2026-05-04-s3-files-benchmark-design.md) (+ Amendment 1)

## 1. 검증 목적
AWS S3 Files 발표가 주장한 **"활성 데이터에 대해 1ms 이하의 지연 시간"** 이 실제 ML/AI 워크로드 패턴(특히 cold cache 조건)에서 성립하는지 정량 검증.

## 2. 실험 셋업

| 항목 | 값 |
|---|---|
| 비교군 | S3 Files / Mountpoint for S3 (v1.22.3) / EFS Standard (TLS+IAM) |
| 워크로드 | fio 4종 (P1 1MiB seq read, P2 4KiB random read, P3 4MiB ckpt write, P4 mixed) |
| 캐시 | **Cold-only** (per-cell `umount`/`remount` + `drop_caches` + unique seed dir) |
| Run | 3회 반복, 60초 측정 + 30초 워밍업 폐기 |
| 인스턴스 | c6gn.xlarge Spot, AZ us-east-1c, AL2023 ARM |

## 3. 가설 검증

### H1 — cold-cache 4KiB random read의 p50 > 1ms일 것이다
**결과**: TBD (측정 후 채움)

### H2 — S3 Files cold seq read는 EFS보다 유의하게 느릴 것이다
**결과**: TBD

### H3 — SageMaker Training Job(Spot)에서 S3 Files는 별도 작업 없이는 마운트되지 않는다
**결과**: TBD

## 4. 지연시간 (cold-cache, 3-run median)

> 차트: [`output/latency_boxplot.png`](../../experiments/s3-files-benchmark/output/latency_boxplot.png)

| Profile | System | p50 (μs) | p99 (μs) | Throughput (MiB/s) |
|---|---|---:|---:|---:|
| TBD | TBD | TBD | TBD | TBD |

## 5. SageMaker 마운트 호환성 (Phase 1 PoC)

상세: [`experiments/s3-files-benchmark/sagemaker/README.md`](../../experiments/s3-files-benchmark/sagemaker/README.md)

요약: TBD

## 6. 한계 및 알려진 변수
- **R4**: "S3 Files를 cold로 보면" 페이지 캐시는 비웠지만 underlying EFS-backed cache는 따뜻할 수 있음. 진정한 S3-cold는 boto3 PUT 후 ImportDataRules 트리거 + cache invalidation이 필요. 본 실험은 mount-write seed 후 cold로 측정한 정직한 한계.
- **EFS IAM 마운트 강제**: CDK feature flag `aws-efs:denyAnonymousAccess`가 file-system policy에 deny anon 정책을 자동 추가 → `-o tls` 단독 마운트는 access denied. 모든 EFS 마운트에 `-o tls,iam` 사용.
- **Mountpoint 1.22.3**: legacy `--no-cache` 플래그는 제거됨; 1.22+ 기본이 client cache 없음. 캐시를 명시적으로 켜려면 `--cache <dir>`.

## 7. 비용 실측
TBD (실험 종료 후 Cost Explorer 추출)

## 8. 검증된 PHASE 2 발견사항 (스펙 가정 vs 실제)
- AWS::S3Files::FileSystem trust principal: **`elasticfilesystem.amazonaws.com`** (S3 Files는 EFS 기반). `s3files.amazonaws.com`는 IAM이 unknown service로 reject. `s3.amazonaws.com`은 IAM은 통과하지만 S3 Files가 실제 assume 시 ERROR state로 떨어짐.
- S3 Files backing bucket은 **versioning 활성화 필수** (`aws s3files create-file-system` 거부 → "Your bucket must have versioning enabled").
- SourceAccount + SourceArn 조건으로 Confused Deputy 방지가 권장 패턴.
