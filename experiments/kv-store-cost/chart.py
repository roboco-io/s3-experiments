"""
S3 vs DynamoDB 비용 교차점 분석 그래프
호출 빈도(일별 요청 수)에 따른 월간 총 비용 비교
"""

import os
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

os.makedirs('output', exist_ok=True)

plt.rcParams['font.family'] = ['Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# ============================================================
# 가격 데이터 (us-east-1, 2026-03 기준)
# ============================================================

# S3 Standard
S3_STD_STORAGE_PER_GB = 0.023        # $/GB/month
S3_STD_GET_PER_REQ    = 0.0000004    # $/request ($0.0004/1K)
S3_STD_PUT_PER_REQ    = 0.000005     # $/request ($0.005/1K)

# S3 Express One Zone (2025.04 가격 인하 후)
S3_EXP_STORAGE_PER_GB = 0.11         # $/GB/month
S3_EXP_GET_PER_REQ    = 0.00000003   # $/request ($0.00003/1K)
S3_EXP_PUT_PER_REQ    = 0.00000113   # $/request ($0.00113/1K)

# DynamoDB On-Demand
DDB_STORAGE_PER_GB    = 0.25         # $/GB/month
DDB_RRU_PER_REQ       = 0.00000025   # $/RRU ($0.25/1M) - strongly consistent, <=4KB
DDB_WRU_PER_REQ       = 0.00000125   # $/WRU ($1.25/1M) - <=1KB


def monthly_cost(daily_reads, daily_writes, storage_gb, value_size_kb,
                 storage_per_gb, read_per_req, write_per_req, is_dynamodb=False):
    """월간 총 비용 계산"""
    # 스토리지
    storage_cost = storage_gb * storage_per_gb

    # DynamoDB는 4KB 초과 시 추가 RRU/WRU 소모
    if is_dynamodb:
        read_units = max(1, int(np.ceil(value_size_kb / 4)))    # 4KB 단위
        write_units = max(1, int(np.ceil(value_size_kb / 1)))   # 1KB 단위
        read_cost = daily_reads * 30 * read_per_req * read_units
        write_cost = daily_writes * 30 * write_per_req * write_units
    else:
        # S3는 객체 크기와 무관하게 요청당 동일 비용
        read_cost = daily_reads * 30 * read_per_req
        write_cost = daily_writes * 30 * write_per_req

    return storage_cost + read_cost + write_cost


# ============================================================
# 그래프 1: 읽기 빈도별 월 비용 (값 크기 1KB, 저장 1GB)
# ============================================================
fig, axes = plt.subplots(2, 2, figsize=(16, 14))

daily_reads = np.logspace(1, 7, 200)  # 10 ~ 10,000,000 reads/day
value_sizes = [1, 4, 16, 64]  # KB
storage_gb = 1

for idx, val_kb in enumerate(value_sizes):
    ax = axes[idx // 2][idx % 2]

    # 읽기:쓰기 = 9:1 가정
    daily_writes = daily_reads * 0.1

    s3_std = [monthly_cost(r, w, storage_gb, val_kb,
              S3_STD_STORAGE_PER_GB, S3_STD_GET_PER_REQ, S3_STD_PUT_PER_REQ)
              for r, w in zip(daily_reads, daily_writes)]

    s3_exp = [monthly_cost(r, w, storage_gb, val_kb,
              S3_EXP_STORAGE_PER_GB, S3_EXP_GET_PER_REQ, S3_EXP_PUT_PER_REQ)
              for r, w in zip(daily_reads, daily_writes)]

    ddb = [monthly_cost(r, w, storage_gb, val_kb,
           DDB_STORAGE_PER_GB, DDB_RRU_PER_REQ, DDB_WRU_PER_REQ, is_dynamodb=True)
           for r, w in zip(daily_reads, daily_writes)]

    ax.loglog(daily_reads, s3_std, 'b-', linewidth=2, label='S3 Standard')
    ax.loglog(daily_reads, s3_exp, 'g-', linewidth=2, label='S3 Express One Zone')
    ax.loglog(daily_reads, ddb, 'r-', linewidth=2, label='DynamoDB On-Demand')

    # 교차점 찾기 (S3 Standard vs DynamoDB)
    s3_arr = np.array(s3_std)
    ddb_arr = np.array(ddb)
    crossover_idx = np.where(np.diff(np.sign(s3_arr - ddb_arr)))[0]
    for ci in crossover_idx:
        cross_x = daily_reads[ci]
        cross_y = s3_std[ci]
        ax.plot(cross_x, cross_y, 'ko', markersize=10, zorder=5)
        ax.annotate(f'  Crossover\n  ~{int(cross_x):,}/day',
                   (cross_x, cross_y), fontsize=9, fontweight='bold',
                   color='black')

    ax.set_xlabel('Daily Read Requests', fontsize=11)
    ax.set_ylabel('Monthly Cost ($)', fontsize=11)
    ax.set_title(f'Value Size = {val_kb}KB  |  Storage = {storage_gb}GB  |  Read:Write = 9:1',
                fontsize=12, fontweight='bold')
    ax.legend(fontsize=10, loc='upper left')
    ax.grid(True, alpha=0.3, which='both')
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f'{int(x):,}'))

    # 영역 색상
    ax.fill_between(daily_reads, 0.001, 1000,
                   where=[s < d for s, d in zip(s3_std, ddb)],
                   alpha=0.05, color='blue', label='_S3 wins')
    ax.fill_between(daily_reads, 0.001, 1000,
                   where=[s >= d for s, d in zip(s3_std, ddb)],
                   alpha=0.05, color='red', label='_DDB wins')

fig.suptitle('S3 vs DynamoDB: Monthly Cost by Daily Read Frequency\n'
             '(us-east-1, Read:Write = 9:1, 2026-03 pricing)',
             fontsize=14, fontweight='bold', y=1.01)
plt.tight_layout()
plt.savefig('output/cost-crossover-by-value-size.png',
            dpi=150, bbox_inches='tight')
plt.close()

# ============================================================
# 그래프 2: 값 크기별 교차점 요약 (핵심 그래프)
# ============================================================
fig, ax = plt.subplots(figsize=(14, 8))

value_sizes_sweep = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
crossover_points_std = []
crossover_points_exp = []

for val_kb in value_sizes_sweep:
    daily_reads_fine = np.logspace(0, 8, 5000)
    daily_writes_fine = daily_reads_fine * 0.1

    s3_std_costs = np.array([monthly_cost(r, w, 1, val_kb,
                   S3_STD_STORAGE_PER_GB, S3_STD_GET_PER_REQ, S3_STD_PUT_PER_REQ)
                   for r, w in zip(daily_reads_fine, daily_writes_fine)])

    s3_exp_costs = np.array([monthly_cost(r, w, 1, val_kb,
                   S3_EXP_STORAGE_PER_GB, S3_EXP_GET_PER_REQ, S3_EXP_PUT_PER_REQ)
                   for r, w in zip(daily_reads_fine, daily_writes_fine)])

    ddb_costs = np.array([monthly_cost(r, w, 1, val_kb,
                DDB_STORAGE_PER_GB, DDB_RRU_PER_REQ, DDB_WRU_PER_REQ, is_dynamodb=True)
                for r, w in zip(daily_reads_fine, daily_writes_fine)])

    # S3 Standard vs DynamoDB 교차점
    cross_std = np.where(np.diff(np.sign(s3_std_costs - ddb_costs)))[0]
    if len(cross_std) > 0:
        crossover_points_std.append(daily_reads_fine[cross_std[0]])
    else:
        # S3가 항상 저렴하면 매우 큰 값, 항상 비싸면 매우 작은 값
        if s3_std_costs[-1] < ddb_costs[-1]:
            crossover_points_std.append(1e8)  # S3 always wins
        else:
            crossover_points_std.append(1)  # DDB always wins

    # S3 Express vs DynamoDB 교차점
    cross_exp = np.where(np.diff(np.sign(s3_exp_costs - ddb_costs)))[0]
    if len(cross_exp) > 0:
        crossover_points_exp.append(daily_reads_fine[cross_exp[0]])
    else:
        if s3_exp_costs[-1] < ddb_costs[-1]:
            crossover_points_exp.append(1e8)
        else:
            crossover_points_exp.append(1)

ax.semilogy(value_sizes_sweep, crossover_points_std, 'b-o', linewidth=2.5,
           markersize=8, label='S3 Standard vs DynamoDB', zorder=3)
ax.semilogy(value_sizes_sweep, crossover_points_exp, 'g-s', linewidth=2.5,
           markersize=8, label='S3 Express vs DynamoDB', zorder=3)

# 영역 표시
ax.fill_between(value_sizes_sweep, 1, crossover_points_std,
               alpha=0.15, color='red', label='DynamoDB cheaper (S3 Std)')
ax.fill_between(value_sizes_sweep, crossover_points_std, 1e8,
               alpha=0.1, color='blue', label='S3 Standard cheaper')

# 주요 값 크기 표시
for i, (vk, cp_std, cp_exp) in enumerate(zip(value_sizes_sweep, crossover_points_std, crossover_points_exp)):
    if vk in [1, 4, 16, 64, 256, 1024]:
        if cp_std < 1e7:
            ax.annotate(f'{int(cp_std):,}/day', (vk, cp_std),
                       textcoords="offset points", xytext=(10, 10),
                       fontsize=9, color='blue', fontweight='bold')
        if cp_exp < 1e7:
            ax.annotate(f'{int(cp_exp):,}/day', (vk, cp_exp),
                       textcoords="offset points", xytext=(10, -15),
                       fontsize=9, color='green', fontweight='bold')

ax.set_xlabel('Value Size (KB)', fontsize=13, fontweight='bold')
ax.set_ylabel('Daily Reads at Cost Crossover Point', fontsize=13, fontweight='bold')
ax.set_title('S3 vs DynamoDB Cost Crossover: At What Read Frequency Does S3 Become Cheaper?\n'
            '(1GB storage, Read:Write = 9:1, us-east-1, 2026-03 pricing)',
            fontsize=13, fontweight='bold')
ax.legend(fontsize=11, loc='upper right')
ax.grid(True, alpha=0.3, which='both')
ax.set_xscale('log', base=2)
ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f'{int(x)}KB'))
ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f'{int(x):,}'))

# 4KB 경계선
ax.axvline(x=4, color='gray', linestyle='--', alpha=0.5)
ax.annotate('DynamoDB 4KB\nRRU boundary', (4, 5e6), fontsize=9,
           color='gray', ha='center')

plt.tight_layout()
plt.savefig('output/cost-crossover-summary.png',
            dpi=150, bbox_inches='tight')
plt.close()

# ============================================================
# 그래프 3: 스토리지 크기별 비용 비교 (고정 빈도)
# ============================================================
fig, ax = plt.subplots(figsize=(12, 7))

storage_sizes = np.logspace(-1, 3, 100)  # 0.1GB ~ 1TB
daily_reads_fixed = 1000
daily_writes_fixed = 100

s3_std_by_storage = [monthly_cost(daily_reads_fixed, daily_writes_fixed, sg, 4,
                     S3_STD_STORAGE_PER_GB, S3_STD_GET_PER_REQ, S3_STD_PUT_PER_REQ)
                     for sg in storage_sizes]

s3_exp_by_storage = [monthly_cost(daily_reads_fixed, daily_writes_fixed, sg, 4,
                     S3_EXP_STORAGE_PER_GB, S3_EXP_GET_PER_REQ, S3_EXP_PUT_PER_REQ)
                     for sg in storage_sizes]

ddb_by_storage = [monthly_cost(daily_reads_fixed, daily_writes_fixed, sg, 4,
                  DDB_STORAGE_PER_GB, DDB_RRU_PER_REQ, DDB_WRU_PER_REQ, is_dynamodb=True)
                  for sg in storage_sizes]

ax.loglog(storage_sizes, s3_std_by_storage, 'b-', linewidth=2.5, label='S3 Standard')
ax.loglog(storage_sizes, s3_exp_by_storage, 'g-', linewidth=2.5, label='S3 Express One Zone')
ax.loglog(storage_sizes, ddb_by_storage, 'r-', linewidth=2.5, label='DynamoDB On-Demand')

ax.set_xlabel('Storage Size (GB)', fontsize=13, fontweight='bold')
ax.set_ylabel('Monthly Cost ($)', fontsize=13, fontweight='bold')
ax.set_title('Monthly Cost by Storage Size\n'
            '(1,000 reads + 100 writes per day, value=4KB, us-east-1)',
            fontsize=13, fontweight='bold')
ax.legend(fontsize=11)
ax.grid(True, alpha=0.3, which='both')
ax.xaxis.set_major_formatter(ticker.FuncFormatter(
    lambda x, p: f'{x:.0f}GB' if x >= 1 else f'{x*1000:.0f}MB'))

plt.tight_layout()
plt.savefig('output/cost-by-storage-size.png',
            dpi=150, bbox_inches='tight')
plt.close()

# ============================================================
# 그래프 4: 스토리지 크기별 비용 비교 (선형 스케일 - 차이 명확)
# ============================================================
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))

# 왼쪽: 0~100GB 구간 (선형)
storage_linear = np.linspace(0.1, 100, 200)

s3_std_lin = [monthly_cost(daily_reads_fixed, daily_writes_fixed, sg, 4,
              S3_STD_STORAGE_PER_GB, S3_STD_GET_PER_REQ, S3_STD_PUT_PER_REQ)
              for sg in storage_linear]
s3_exp_lin = [monthly_cost(daily_reads_fixed, daily_writes_fixed, sg, 4,
              S3_EXP_STORAGE_PER_GB, S3_EXP_GET_PER_REQ, S3_EXP_PUT_PER_REQ)
              for sg in storage_linear]
ddb_lin = [monthly_cost(daily_reads_fixed, daily_writes_fixed, sg, 4,
           DDB_STORAGE_PER_GB, DDB_RRU_PER_REQ, DDB_WRU_PER_REQ, is_dynamodb=True)
           for sg in storage_linear]

ax1.plot(storage_linear, ddb_lin, 'r-', linewidth=2.5, label='DynamoDB On-Demand')
ax1.plot(storage_linear, s3_exp_lin, 'g-', linewidth=2.5, label='S3 Express One Zone')
ax1.plot(storage_linear, s3_std_lin, 'b-', linewidth=2.5, label='S3 Standard')

ax1.fill_between(storage_linear, s3_std_lin, ddb_lin, alpha=0.15, color='green',
                label='Cost savings vs DynamoDB')

# 주요 포인트 표시
for sg_point in [10, 50, 100]:
    idx = np.argmin(np.abs(storage_linear - sg_point))
    s3_val = s3_std_lin[idx]
    ddb_val = ddb_lin[idx]
    ratio = ddb_val / s3_val
    ax1.annotate(f'{sg_point}GB:\nDDB ${ddb_val:.1f}\nS3 ${s3_val:.2f}\n({ratio:.0f}x diff)',
                (sg_point, ddb_val), textcoords="offset points", xytext=(-50, 10),
                fontsize=8, fontweight='bold', color='darkred',
                arrowprops=dict(arrowstyle='->', color='gray', lw=0.8))

ax1.set_xlabel('Storage Size (GB)', fontsize=12, fontweight='bold')
ax1.set_ylabel('Monthly Cost ($)', fontsize=12, fontweight='bold')
ax1.set_title('0 ~ 100GB (Linear Scale)', fontsize=12, fontweight='bold')
ax1.legend(fontsize=9, loc='upper left')
ax1.grid(True, alpha=0.3)

# 오른쪽: 비용 배율 그래프
storage_ratio = np.linspace(1, 1000, 200)

ratios_std = []
ratios_exp = []
for sg in storage_ratio:
    s3_c = monthly_cost(daily_reads_fixed, daily_writes_fixed, sg, 4,
           S3_STD_STORAGE_PER_GB, S3_STD_GET_PER_REQ, S3_STD_PUT_PER_REQ)
    s3e_c = monthly_cost(daily_reads_fixed, daily_writes_fixed, sg, 4,
            S3_EXP_STORAGE_PER_GB, S3_EXP_GET_PER_REQ, S3_EXP_PUT_PER_REQ)
    ddb_c = monthly_cost(daily_reads_fixed, daily_writes_fixed, sg, 4,
            DDB_STORAGE_PER_GB, DDB_RRU_PER_REQ, DDB_WRU_PER_REQ, is_dynamodb=True)
    ratios_std.append(ddb_c / s3_c)
    ratios_exp.append(ddb_c / s3e_c)

ax2.plot(storage_ratio, ratios_std, 'b-', linewidth=2.5, label='DynamoDB / S3 Standard')
ax2.plot(storage_ratio, ratios_exp, 'g-', linewidth=2.5, label='DynamoDB / S3 Express')
ax2.axhline(y=1, color='gray', linestyle='--', alpha=0.5, label='Break-even (1x)')

ax2.set_xlabel('Storage Size (GB)', fontsize=12, fontweight='bold')
ax2.set_ylabel('Cost Ratio (DynamoDB / S3)', fontsize=12, fontweight='bold')
ax2.set_title('How Many Times More Expensive is DynamoDB?', fontsize=12, fontweight='bold')
ax2.legend(fontsize=10, loc='center right')
ax2.grid(True, alpha=0.3)

# 주요 포인트 표시
for sg_pt in [10, 100, 500, 1000]:
    idx = np.argmin(np.abs(storage_ratio - sg_pt))
    ax2.annotate(f'{ratios_std[idx]:.1f}x', (sg_pt, ratios_std[idx]),
                textcoords="offset points", xytext=(5, 10),
                fontsize=10, fontweight='bold', color='blue')

fig.suptitle('S3 vs DynamoDB: Storage Cost Difference (Linear Scale)\n'
            '(1,000 reads + 100 writes per day, value=4KB, us-east-1)',
            fontsize=13, fontweight='bold', y=1.02)
plt.tight_layout()
plt.savefig('output/cost-by-storage-linear.png',
            dpi=150, bbox_inches='tight')
plt.close()

print("4개 그래프 생성 완료:")
print("  1. cost-crossover-by-value-size.png  - 값 크기별 빈도-비용 곡선 (4 panels)")
print("  2. cost-crossover-summary.png        - 교차점 요약 (핵심 그래프)")
print("  3. cost-by-storage-size.png           - 스토리지 크기별 비용")
