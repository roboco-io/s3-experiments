"""Render latency boxplot + throughput bar chart from summary.csv.

Output:
  ../output/latency_boxplot.png   latency p50/p95/p99 grouped by system × profile
  ../output/throughput_bar.png    median throughput per system × profile
"""
from __future__ import annotations
import csv
from collections import defaultdict
from pathlib import Path
from statistics import median

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

OUTPUT_DIR = Path(__file__).resolve().parent.parent / 'output'
SUMMARY = OUTPUT_DIR / 'summary.csv'

SYSTEMS = ['s3files', 'mountpoint', 'efs']
PROFILES = ['p1_shard_seq_read', 'p2_random_read_4k', 'p3_checkpoint_write', 'p4_mixed_train']
COLORS = {'s3files': '#FF9900', 'mountpoint': '#1f77b4', 'efs': '#2ca02c'}


def load() -> list[dict]:
    if not SUMMARY.exists():
        raise SystemExit(f'missing {SUMMARY} — run parse_fio.py first')
    with SUMMARY.open() as f:
        return list(csv.DictReader(f))


def aggregate(rows: list[dict]) -> dict:
    """{(system, profile): {'p50':[..], 'p95':[..], 'p99':[..], 'mibs':[..]}}"""
    agg = defaultdict(lambda: defaultdict(list))
    for r in rows:
        key = (r['system'], r['profile'])
        agg[key]['p50'].append(float(r['lat_p50_us']) / 1000.0)  # ms
        agg[key]['p95'].append(float(r['lat_p95_us']) / 1000.0)
        agg[key]['p99'].append(float(r['lat_p99_us']) / 1000.0)
        agg[key]['mibs'].append(float(r['throughput_mibs']))
    return agg


def plot_latency(agg: dict) -> None:
    fig, axes = plt.subplots(1, len(PROFILES), figsize=(16, 5), sharey=False)
    for i, profile in enumerate(PROFILES):
        ax = axes[i]
        positions = []
        labels = []
        data = []
        colors = []
        for j, sys in enumerate(SYSTEMS):
            samples = agg.get((sys, profile), {}).get('p99', [])
            if not samples:
                continue
            positions.append(j)
            labels.append(sys)
            data.append(samples)
            colors.append(COLORS[sys])
        if data:
            bp = ax.boxplot(data, positions=positions, patch_artist=True,
                            widths=0.6, showmeans=True)
            for patch, c in zip(bp['boxes'], colors):
                patch.set_facecolor(c)
                patch.set_alpha(0.6)
            ax.set_xticks(positions)
            ax.set_xticklabels(labels, rotation=20, ha='right')
        ax.set_title(profile.replace('_', ' '))
        ax.set_ylabel('p99 latency (ms)')
        ax.axhline(1.0, color='red', ls='--', lw=0.7, label='AWS "1 ms" claim')
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(True, axis='y', alpha=0.3)
    fig.suptitle('Cold-cache p99 latency — S3 Files vs Mountpoint vs EFS', fontsize=13)
    fig.tight_layout()
    out = OUTPUT_DIR / 'latency_boxplot.png'
    fig.savefig(out, dpi=120)
    print(f'wrote {out}')


def plot_throughput(agg: dict) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    width = 0.25
    x = np.arange(len(PROFILES))
    for i, sys in enumerate(SYSTEMS):
        medians = [median(agg.get((sys, p), {}).get('mibs', [0])) for p in PROFILES]
        ax.bar(x + (i - 1) * width, medians, width, label=sys,
               color=COLORS[sys], alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels([p.replace('_', '\n') for p in PROFILES])
    ax.set_ylabel('Throughput (MiB/s)')
    ax.set_title('Median throughput per profile (cold cache, 3-run median)')
    ax.legend()
    ax.grid(True, axis='y', alpha=0.3)
    fig.tight_layout()
    out = OUTPUT_DIR / 'throughput_bar.png'
    fig.savefig(out, dpi=120)
    print(f'wrote {out}')


def main() -> None:
    rows = load()
    agg = aggregate(rows)
    plot_latency(agg)
    plot_throughput(agg)


if __name__ == '__main__':
    main()
