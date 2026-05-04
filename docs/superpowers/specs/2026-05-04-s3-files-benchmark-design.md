# S3 Files Performance Benchmark — 실험 설계 (Spec)

- **작성일**: 2026-05-04
- **저자**: Jung Do Hyun (with Claude)
- **상태**: Draft (사용자 검토 대기)
- **관련 패턴**: 패턴 5 — `S3 as File I/O`
- **레퍼런스**:
  - [AWS 발표(한글) — Launching S3 Files](https://aws.amazon.com/ko/blogs/korea/launching-s3-files-making-s3-buckets-accessible-as-file-systems/)
  - [`docs/research/file-io.md`](../../research/file-io.md)

---

## 1. 목적·가설·결과물

### 1.1 목적
AWS S3 Files 발표가 주장한 **"활성 데이터에 대해 1ms 이하의 지연 시간"** 이 실제 ML/AI 워크로드 패턴(특히 cold cache 조건)에서 성립하는지 정량 검증한다. 동시에 "S3 버킷을 파일시스템처럼"이라는 동일 비전을 제시하는 두 선행 기술(Mountpoint for S3, EFS Standard)과 같은 평면에서 비교하여 패턴 5(`S3 as File I/O`) 결정 가이드를 갱신한다.

### 1.2 핵심 가설
- **H1**: cold-cache 조건의 4KB random read에서 세 시스템 모두 **p50 > 1ms** 일 것이다. AWS 마케팅 수치는 warm-cache 한정으로 추정된다.
- **H2**: S3 Files는 cold sequential read에서 EFS Standard보다 **유의하게 느리고**, Mountpoint for S3와 비슷할 것이다 (둘 다 underlying이 S3 객체 fetch).
- **H3**: SageMaker Training Job(Spot)에서 S3 Files는 별도 작업 없이는 마운트되지 않는다 (VPC mode 강제, EFS 드라이버 패키지 필요, kernel module 의존성).

### 1.3 결과물
- `experiments/s3-files-benchmark/` — fio jobfile + 실행 스크립트 + CDK 스택
- `docs/research/s3-files.md` — 결과 요약, 표·차트, 결정 가이드
- `docs/research/file-io.md` 갱신 — 표 2.3, 6.2 등에 S3 Files 행 추가
- `README.md` 패턴 5 줄에 "S3 Files 비교 추가" 표시

---

## 2. 비교군·변수 통제·메트릭

### 2.1 비교군 (3way, 동일 us-east-1 / 동일 AZ / 동일 클라이언트)

| 시스템 | 마운트 방식 | 비용 모델 | 비고 |
|---|---|---|---|
| **S3 Files** | `mount -t s3files fs-XXX:/ /mnt/s3files` (`amazon-efs-utils` 최신) | S3 Standard 스토리지 + 요청 + 동기화 트래픽 | 신규 검증 대상 |
| **Mountpoint for S3** | `mount-s3 BUCKET /mnt/mountpoint --no-cache` | S3 Standard 동일 | FUSE 기반 |
| **EFS Standard** | `mount -t efs fs-YYY:/ /mnt/efs` | EFS Standard 스토리지 + 처리량 | "친척" baseline |

> Mountpoint는 GA 후 옵션 캐시 확장 → `--no-cache` 명시. EFS는 client-side cache 비활성화 어려움 → 매 run `umount`/`remount`로 cold 강제.

### 2.2 변수 통제
- 동일 파일 트리 구조(같은 디렉토리 깊이, 같은 파일 수, 같은 평균 크기) 사전 시드.
- 매 fio iteration 전 `sync && echo 3 > /proc/sys/vm/drop_caches` 실행.
- 매 read 대상은 unique 파일 — 한 번 읽은 파일 재사용 금지 (`--filename` 매번 회전).
- Run당 60초 측정 + 30초 워밍업 → 워밍업 데이터 폐기.
- 각 (system × profile) 조합 **3 run** 반복, 중앙값 + 분산 보고.
- 인스턴스: c6gn.xlarge (10 Gbps, ARM Graviton2) — `file-io.md`의 기존 벤치 환경과 일치.

### 2.3 메트릭
- **지연시간**: p50, p95, p99, p99.9, max (μs 단위, fio 직접 보고)
- **처리량**: MB/s, IOPS
- **클라이언트 CPU**: `mpstat` 기록 — NFS/FUSE 오버헤드 가시화
- **비용**: 실험 종료 후 Cost Explorer 1일치 추출

### 2.4 보고 양식
- Raw fio JSON 보존 (`output/raw/`)
- `output/summary.csv` — system, profile, run, p50/p95/p99/throughput
- 마크다운 표 + matplotlib 박스플롯 PNG 2종 (latency 분포, throughput)

---

## 3. fio 프로파일 4종

각 프로파일은 같은 jobfile을 세 마운트 포인트(`/mnt/s3files`, `/mnt/mountpoint`, `/mnt/efs`)에 그대로 적용.

### P1. shard-seq-read — 대용량 순차 읽기 (가장 S3 친화적)
```ini
[shard-seq-read]
rw=read
bs=1M
size=512M
iodepth=16
numjobs=4
direct=1
group_reporting=1
runtime=60s
ramp_time=30s
filename_format=$jobnum/$filenum
nrfiles=8
```

### P2. random-read-4k — 랜덤 소형 읽기 (H1 핵심 검증)
```ini
[random-read-4k]
rw=randread
bs=4K
size=64M
iodepth=64
numjobs=2
direct=1
runtime=60s
ramp_time=30s
filename_format=$jobnum/$filenum
nrfiles=64
```

### P3. checkpoint-write — 대용량 쓰기 (S3 Files의 S3 동기화 가시성)
```ini
[checkpoint-write]
rw=write
bs=4M
size=1G
iodepth=4
numjobs=1
fsync_on_close=1
end_fsync=1
runtime=60s
ramp_time=30s
```

### P4. mixed-train — 혼합 (학습 step 모사)
```ini
[mixed-read]
rw=randread
bs=64K
size=128M
iodepth=32
numjobs=2
direct=1
runtime=60s

[mixed-write]
rw=write
bs=4M
size=256M
iodepth=2
numjobs=1
end_fsync=1
runtime=60s
```

### Cold 강제 절차 (각 run 시작 시 자동)
```bash
sync; echo 3 | sudo tee /proc/sys/vm/drop_caches
sudo umount /mnt/{s3files,mountpoint,efs}
mount -t s3files ...; mount-s3 ... --no-cache; mount -t efs ...
SEED_DIR=run-$(uuidgen)
```

### 가설별 매핑
| 프로파일 | 가설 | 사전 기대 |
|---|---|---|
| P2 random-read-4k | H1 (1ms 이하?) | S3 Files p50 50–200ms |
| P1 shard-seq-read | H2 (S3 Files vs EFS) | EFS가 2–5배 빠름 |
| P3 checkpoint-write | 부수적 | S3 Files write→S3 동기화 지연 가시화 |
| P4 mixed-train | 부수적 | Mountpoint write 제한 노출 가능성 |

### 호환성 fallback
첫 dry-run에서 `direct=1` (O_DIRECT)이 NFSv4/FUSE에서 거부되면 → 모든 프로파일에서 `direct=0` + 매 run마다 `drop_caches`로 변경. 이 변경은 결과 보고서에 명시.

---

## 4. Phase 1 (SageMaker Spot PoC) + Phase 2 (EC2 측정)

### 4.1 Phase 1 — SageMaker Training Job(Spot) 호환성 PoC

**목적**: "AWS가 GPU/HPC 비권장이라 명시한 S3 Files를 SageMaker Spot에 어떻게든 마운트할 수 있는가"의 Y/N + 제약 문서화. 측정은 부수.

| # | 컨테이너 | VPC mode | 시도 | 사전 기대 |
|---|---|---|---|---|
| T1 | DLC PyTorch 2.x (CPU, ml.m5.xlarge) | OFF | `mount -t s3files` | 실패 (네트워크 격리) — 기준선 |
| T2 | DLC PyTorch 2.x (CPU, ml.m5.xlarge) | ON, subnet+SG | `mount -t s3files` | 가장 가능성 높음 |
| T3 | DLC PyTorch 2.x (GPU, ml.g5.xlarge) | ON | T2 성공 후 동일 | GPU 환경 호환 검증 |
| T4 | T2 환경 + Spot interruption 강제 (`max_run=300s`) | ON | mount 유지·재마운트 동작 관찰 | 코너 케이스 |

**산출물 (성공/실패 무관)**
- `experiments/s3-files-benchmark/sagemaker/` — train.py(마운트만 시도), `entry_point.sh`, requirements
- `docs/research/s3-files.md`의 "SageMaker 호환성" 절 — 각 셀 결과 + IAM/SG/패키지 + 실패 시 에러 로그
- "실패"가 결과인 경우도 정직하게 보고 (negative result도 publish 가치)

**Phase 1 진입·종료 조건**
- 진입: Phase 2 인프라 코드 완성 전, 별도 SM Notebook에서 빠르게 시도
- 종료: T1~T4 4셀 결과 표 작성 완료. T2 실패 시 SageMaker 차원은 "비호환" 결론으로 마무리하고, EC2 fio 측정(Phase 2)만 진행.

### 4.2 Phase 2 — EC2 측정

**환경**
- Region: us-east-1 (기존 벤치 일관성)
- 인스턴스: **c6gn.xlarge Spot** (4 vCPU, 8GB RAM, 25 Gbps burst, 10 Gbps baseline)
  - `MaxPrice`: on-demand 대비 70%
  - 단일 AZ (단명 잡)
- AMI: Amazon Linux 2023 (file-io.md의 Mountpoint 2025.11 통합 환경과 일치)
- 마운트 클라이언트: `amazon-efs-utils` 최신 + `mount-s3` 최신 + `nfs-utils`

**실행 시나리오 (3 run, 각 cold-only)**
```python
for run in 1..3:
  for system in [s3files, mountpoint, efs]:
    for profile in [P1, P2, P3, P4]:
      cold_setup(system)
      fio --output-format=json+ --output=raw/${run}_${system}_${profile}.json profile.fio
      mpstat 1 60 > raw/${run}_${system}_${profile}_cpu.txt
      sync_to_efs raw/  # Spot 중단 보호
```
총 36 측정. 각 90초(워밍업 30 + 측정 60) → ~54분 fio + 셋업 → **약 2시간 30분**.

### 4.3 Spot 중단 보호
- 매 fio 셀 종료 직후 raw JSON을 EFS로 즉시 sync
- IMDS Spot interruption notice 폴링 → 마지막 셀 결과 EFS 강제 flush
- `output/checkpoint.json` (완료된 (run, system, profile) 기록) → 재시작 시 미완료분만 실행

---

## 5. 인프라·디렉토리·예산·자동 정리

### 5.1 디렉토리 레이아웃

```
experiments/s3-files-benchmark/
├── README.md
├── Makefile                        # deploy / seed / run / collect / destroy / verify-clean
├── cdk/
│   ├── bin/app.ts
│   ├── lib/
│   │   ├── network-stack.ts        # VPC + subnet + SG (NFS 2049 ingress)
│   │   ├── storage-stack.ts        # S3 Files filesystem, EFS, S3 bucket
│   │   ├── client-stack.ts         # c6gn.xlarge Spot EC2 + IAM + UserData
│   │   ├── cleanup-stack.ts        # 24h 자동 destroy Lambda + EventBridge
│   │   └── budget-stack.ts         # AWS Budgets + SNS topic + auto-destroy hook
│   ├── cdk.json
│   ├── package.json
│   └── tsconfig.json
├── scripts/
│   ├── 00_install.sh               # amazon-efs-utils, mount-s3, fio, jq, sysstat
│   ├── 10_mount_all.sh             # 세 시스템 마운트
│   ├── 20_seed.sh                  # 동일 트리 사전 시드
│   ├── 30_cold_setup.sh            # umount/remount + drop_caches + unique dir
│   ├── 40_run_one.sh               # 한 (run, system, profile) 실행
│   ├── 45_save_checkpoint.sh       # Spot 중단 대비 체크포인트
│   ├── 50_run_all.sh               # 36 셀 시퀀스 + raw 수집
│   ├── 90_destroy.sh               # 마운트 해제, 시드 정리
│   └── 99_verify_clean.sh          # 정리 검증
├── fio/
│   ├── p1_shard_seq_read.fio
│   ├── p2_random_read_4k.fio
│   ├── p3_checkpoint_write.fio
│   └── p4_mixed_train.fio
├── sagemaker/
│   ├── train.py
│   ├── entry_point.sh
│   ├── launch_t1_t4.py
│   └── README.md
├── analysis/
│   ├── parse_fio.py
│   ├── plots.py
│   └── compare_table.py
└── output/
    ├── raw/
    ├── summary.csv
    ├── latency_boxplot.png
    ├── throughput_bar.png
    └── results.md
```

### 5.2 자동 정리 (다층 안전장치)

| 계층 | 메커니즘 | 트리거 |
|---|---|---|
| 1 | `make destroy` — 명시적 호출 | 실험 종료 후 사용자가 1회 실행 |
| 2 | EC2 UserData 종료 트랩 | `50_run_all.sh` 정상 종료 시 자기 자신을 `shutdown -h now` |
| 3 | EC2 `InstanceInitiatedShutdownBehavior=terminate` | 스스로 셧다운 시 자동 종료 |
| 4 | CDK Lambda + EventBridge: 24h 후 모든 스택 자동 destroy | destroy 호출 누락 안전망 |
| 5 | S3 Files / EFS / S3 — `RemovalPolicy.DESTROY` + `autoDeleteObjects: true` | destroy 시 강제 정리 |
| 6 | `make verify-clean` — 남은 리소스 grep | 사람 검증 |

### 5.3 예상 비용 (2026-05 us-east-1 기준)

| 리소스 | 단가 | 사용량 | 비용 |
|---|---|---|---|
| c6gn.xlarge **Spot** | $0.030/h | 8h | $0.24 |
| EFS Standard | $0.30/GB·월 | 5GB × 1일 | $0.05 |
| S3 Files (= S3 backed) | $0.023/GB·월 + 요청 | 5GB × 1일 + 요청 | $0.30 |
| S3 Standard (Mountpoint) | $0.023/GB·월 | 5GB × 1일 | $0.004 |
| S3 PUT (시드 + 동기화) | $0.005/1K | ~50K | $0.25 |
| S3 GET (cold reads) | $0.0004/1K | ~500K | $0.20 |
| SageMaker ml.g5.xlarge **Spot** | $0.36/h | 0.5h | $0.18 |
| SageMaker ml.m5.xlarge **Spot** | $0.06/h | 1h | $0.06 |
| Lambda(자동 정리) + EventBridge | 무시 가능 | — | <$0.01 |
| **합계 (예상)** | | | **~$1.3** |

### 5.4 비용 가드(하드 캡)
- AWS Budget Alert: 일일 **$5** 초과 시 SNS + 자동 stack destroy Lambda 트리거
- 단일 세션 절대 상한 **$10**

### 5.5 소요 시간 (벤치 본 실행)
- CDK 작성·디버그: 4h
- 시드·마운트 스크립트: 2h
- Phase 1 SM PoC 4셀: 1.5h
- Phase 2 fio 36셀 본 실행: 2.5h
- 분석·차트·문서화: 4h
- **총 ~14h** (1.5–2 작업일)

---

## 6. 리스크·실패 처리·완료 기준

### 6.1 기술 리스크 매트릭스

| # | 리스크 | 확률 | 영향 | 대응 |
|---|---|---|---|---|
| R1 | `mount -t s3files`가 SageMaker DLC 컨테이너에서 동작 안 함 | 중 | Phase 1 일부 | T2~T4 결과를 "비호환 + 원인" 문서화 — 그 자체가 결과 |
| R2 | fio `direct=1`이 NFSv4/FUSE에서 거부 | 중 | 모든 fio | 첫 dry-run에서 거부 시 `direct=0` + `drop_caches` |
| R3 | EFS client-side cache가 `umount`/`remount`로도 안 비워짐 | 낮 | EFS 결과 신뢰도 | 매 run unique 디렉토리 + unique 파일명으로 회피 |
| R4 | S3 Files의 백엔드 EFS도 자체 캐시 보유 | 중 | H1 검증 정직성 | "S3-cold but EFS-backend-warm"임을 명시. 이 한계는 보고서에 명문화 |
| R5 | Spot 중단으로 36셀 일부 손실 | 낮 | 일정 +30분 | checkpoint.json으로 미완료분만 재실행 |
| R6 | S3 Files가 us-east-1 일부 AZ에서만 가능 | 낮 | AZ 재선택 | CDK에서 AZ 미지정 → 자동 fallback |
| R7 | CDK destroy가 EFS mount target 의존성으로 실패 | 중 | 비용 누수 | 24h 자동 destroy Lambda가 안전망. `make verify-clean` |
| R8 | 마케팅 수치보다 훨씬 빠른 결과 (H1 기각) | 낮 | 보고서 방향 | "AWS 주장 검증됨"으로 보고. 가설 기각도 정상 |

### 6.2 완료 기준 (Definition of Done)

**Phase 1 (SM PoC)**
- [ ] T1~T4 4셀 결과가 `sagemaker/README.md`에 표로 기록됨 (성공/실패 무관)
- [ ] T2 성공 시 사용된 IAM role, SG, subnet, 패키지 버전 모두 명시

**Phase 2 (EC2 fio)**
- [ ] 36셀(3 run × 3 system × 4 profile) 모두 raw JSON 보존
- [ ] 단일 셀 실패 시 ≥ 2 run 결과 보존하고 사유 기록
- [ ] `summary.csv` 자동 생성 + 두 PNG 차트 생성

**문서화**
- [ ] `docs/research/s3-files.md` 작성 — 가설별 결론, 표, 차트, 한계(특히 R4)
- [ ] `docs/research/file-io.md` 갱신 — 표 2.3 (레이턴시 비교), 표 6.2 (파일 락킹) 등에 S3 Files 행 추가
- [ ] `README.md` 패턴 5 줄에 "S3 Files 비교 추가됨" 표시

**정리**
- [ ] `make verify-clean` 통과 (남은 EC2/EFS/S3/SageMaker/Lambda/EventBridge 모두 0)
- [ ] AWS Cost Explorer로 실제 비용 확인 + 본 spec에 "actual cost" 기록

### 6.3 Out of Scope (의도적 제외)
- warm-cache 측정 — 별도 후속 실험으로 분리
- 다중 클라이언트 fan-out / 잠금 / append 시맨틱 — 후속 실험
- GPU 학습 실제 수행 — Phase 1은 mount만, fio는 CPU 인스턴스
- S3 Express One Zone 비교 — 본 실험은 "S3-as-FS" 3way에 집중

---

## 7. 변경 이력
- 2026-05-04: 초안 작성 (Claude + Jung Do Hyun 인터뷰 기반)
- 2026-05-04 (개정 1): Ralph iteration 2에서 발견한 차단 요인 검증 결과 반영. 아래 Amendment 1 참고.

---

## Amendment 1 — S3 Files API/CFN 검증 결과 (2026-05-04)

### A1.1 검증 트리거
Ralph iteration 2에서 `storage-stack.ts` 작성을 시도하다 "S3 Files를 CDK construct로 어떻게 정의하나"를 결정 못 하고 멈춤. 환경 AWS CLI 2.26.1에는 `s3files` 서브커맨드 부재. 사용자가 AWS CLI 2.34.41로 업그레이드 후 재검증.

### A1.2 검증된 사실
- **AWS CLI**: `aws s3files <subcommand>` 정식 등록 (CLI 2.34.41+)
- **CloudFormation 리소스**: 두 타입 모두 PUBLIC / FULLY_MUTABLE / LIVE
  - `AWS::S3Files::FileSystem` — 필수: `Bucket` (S3 ARN), `RoleArn` (IAM)
  - `AWS::S3Files::MountTarget` — 필수: `FileSystemId`, `SubnetId`; 선택: `SecurityGroups`
- **CDK L1 construct**: `aws-cdk-lib@2.252.0` 기준 `aws_s3files.CfnFileSystem`/`CfnMountTarget` 가용성 미검증, 필요 시 `cdk.CfnResource({ type: 'AWS::S3Files::FileSystem', ... })`로 raw 정의 가능
- **공식 설명**: *"S3 Files makes S3 buckets accessible as high-performance file systems powered by EFS … sub-millisecond latencies through mount targets, supporting AI/ML workloads"*

### A1.3 아키텍처 변경 사항

**a) Bucket 분리 (변수 통제)**
원안의 "S3 Files filesystem + Mountpoint용 별도 bucket"을 명시적으로 두 개의 분리된 bucket으로 변경:
- **Bucket A** (`s3files-bench-{account}-A`) — S3 Files filesystem의 backing store
- **Bucket B** (`s3files-bench-{account}-B`) — Mountpoint for S3가 직접 마운트할 대상
- 같은 시드 트리를 두 bucket에 동일하게 시드 (`scripts/20_seed.sh`가 양쪽에 시드)
- 같은 bucket을 두 인터페이스에서 동시 마운트하지 않음 (캐시·일관성 변수 오염 방지)

**b) IAM 추가**
S3 Files 서비스용 IAM Role 추가 (`storage-stack.ts`):
- Trust: `s3files.amazonaws.com`
- Policy: Bucket A에 대한 `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket`, `s3:GetBucketLocation` + KMS 권한 (KMS 사용 시)

**c) MountTarget per AZ**
`AWS::S3Files::MountTarget`을 client-stack의 EC2가 위치한 동일 AZ에 1개 생성. NFS 2049 ingress SG 부착.

**d) SynchronizationConfiguration**
`AWS::S3Files::FileSystem`의 SynchronizationConfiguration은 cold-cache 검증의 정직성에 영향:
- **ImportDataRules**: `Trigger=ON_DIRECTORY_FIRST_ACCESS`, `Prefix=""`, `SizeLessThan=1073741824` (1GiB)
  - cold 시나리오에서 첫 접근 시점에 import 트리거 — fio cold 측정에 부합
- **ExpirationDataRules**: `DaysAfterLastAccess=30` (실험 단명 기간 동안 무관)

### A1.4 디렉토리 변경
- `cdk/lib/storage-stack.ts` 책임이 늘어남: bucket A, bucket B, S3 Files IAM Role, S3 Files FileSystem, S3 Files MountTarget, EFS, EFS MountTarget — 단일 파일 유지하되 함수 분리
- `scripts/20_seed.sh` — 동일 시드를 bucket A와 bucket B에 모두 적용

### A1.5 검증 누락에 대한 메모
원 spec 작성 단계에서 "S3 Files가 CDK/CLI로 정의 가능한가"를 가정만 하고 검증하지 않음. 다음 spec부터는 brainstorm 직후 핵심 인프라 가용성을 1차로 검증할 것.
