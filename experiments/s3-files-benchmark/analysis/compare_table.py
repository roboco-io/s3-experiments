"""Render a markdown comparison table from summary.csv suitable for
docs/research/s3-files.md and docs/research/file-io.md.
"""
from __future__ import annotations
import csv
from collections import defaultdict
from pathlib import Path
from statistics import median

OUTPUT_DIR = Path(__file__).resolve().parent.parent / 'output'
SUMMARY = OUTPUT_DIR / 'summary.csv'
OUT = OUTPUT_DIR / 'comparison_table.md'

SYSTEMS = ['s3files', 'mountpoint', 'efs']
PROFILES = ['p1_shard_seq_read', 'p2_random_read_4k', 'p3_checkpoint_write', 'p4_mixed_train']


def load() -> list[dict]:
    if not SUMMARY.exists():
        raise SystemExit(f'missing {SUMMARY} — run parse_fio.py first')
    with SUMMARY.open() as f:
        return list(csv.DictReader(f))


def main() -> None:
    rows = load()
    agg = defaultdict(lambda: defaultdict(list))
    for r in rows:
        agg[(r['system'], r['profile'])]['p50'].append(float(r['lat_p50_us']))
        agg[(r['system'], r['profile'])]['p99'].append(float(r['lat_p99_us']))
        agg[(r['system'], r['profile'])]['mibs'].append(float(r['throughput_mibs']))

    lines = []
    lines.append('# S3 Files Benchmark — Cold-Cache Comparison (3-run median)\n')
    lines.append('| Profile | System | p50 latency (μs) | p99 latency (μs) | Throughput (MiB/s) |')
    lines.append('|---|---|---:|---:|---:|')
    for profile in PROFILES:
        for sys in SYSTEMS:
            d = agg.get((sys, profile))
            if not d:
                lines.append(f'| {profile} | {sys} | — | — | — |')
                continue
            p50 = round(median(d['p50']), 1)
            p99 = round(median(d['p99']), 1)
            mibs = round(median(d['mibs']), 1)
            lines.append(f'| {profile} | {sys} | {p50} | {p99} | {mibs} |')
    OUT.write_text('\n'.join(lines) + '\n')
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
