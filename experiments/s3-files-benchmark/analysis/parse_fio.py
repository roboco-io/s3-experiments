"""Parse raw fio JSON output into a tidy summary.csv.

Input:  ../output/raw/{run}_{system}_{profile}.json
Output: ../output/summary.csv

Columns: run, system, profile, job, iops, throughput_mibs,
         lat_p50_us, lat_p95_us, lat_p99_us, lat_p999_us, lat_max_us,
         clat_mean_us, fallback_direct
"""
from __future__ import annotations
import csv
import json
import re
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / 'output'
RAW_DIR = OUTPUT_DIR / 'raw'
SUMMARY = OUTPUT_DIR / 'summary.csv'

CELL_RE = re.compile(r'^(?P<run>\d+)_(?P<system>[a-z]+)_(?P<profile>p\d+_[a-z_]+)\.json$')

PERCENTILES = ['50.000000', '95.000000', '99.000000', '99.900000']


def lat_us(job: dict, key: str = 'clat_ns') -> dict:
    """Extract latency in microseconds from fio json+ output."""
    lat = job.get(key, {})
    pct = lat.get('percentile', {})
    return {
        'p50': pct.get('50.000000', 0) / 1000.0,
        'p95': pct.get('95.000000', 0) / 1000.0,
        'p99': pct.get('99.000000', 0) / 1000.0,
        'p999': pct.get('99.900000', 0) / 1000.0,
        'max': lat.get('max', 0) / 1000.0,
        'mean': lat.get('mean', 0) / 1000.0,
    }


def parse_one(path: Path) -> list[dict]:
    m = CELL_RE.match(path.name)
    if not m:
        return []
    meta = m.groupdict()

    fallback_path = path.with_suffix('.fallback.json')
    fallback_direct = None
    if fallback_path.exists():
        try:
            fallback_direct = json.loads(fallback_path.read_text()).get('fallback_direct')
        except Exception:
            pass

    try:
        data = json.loads(path.read_text())
    except Exception as e:
        print(f'[parse] {path.name}: {e}')
        return []

    rows = []
    for job in data.get('jobs', []):
        # fio reports per direction (read/write); use the dominant one per job
        direction = 'read' if job.get('read', {}).get('total_ios', 0) > 0 else 'write'
        d = job.get(direction, {})
        if d.get('total_ios', 0) == 0:
            continue
        lat = lat_us(d)
        rows.append({
            'run': int(meta['run']),
            'system': meta['system'],
            'profile': meta['profile'],
            'job': job.get('jobname', '?'),
            'direction': direction,
            'iops': round(d.get('iops', 0.0), 2),
            'throughput_mibs': round(d.get('bw', 0) / 1024.0, 2),
            'lat_p50_us': round(lat['p50'], 2),
            'lat_p95_us': round(lat['p95'], 2),
            'lat_p99_us': round(lat['p99'], 2),
            'lat_p999_us': round(lat['p999'], 2),
            'lat_max_us': round(lat['max'], 2),
            'lat_mean_us': round(lat['mean'], 2),
            'fallback_direct': fallback_direct,
        })
    return rows


def main() -> None:
    if not RAW_DIR.is_dir():
        raise SystemExit(f'no raw dir at {RAW_DIR}')
    all_rows = []
    files = sorted(RAW_DIR.glob('*.json'))
    for f in files:
        if f.name.endswith('.fallback.json'):
            continue
        all_rows.extend(parse_one(f))

    if not all_rows:
        raise SystemExit('no rows parsed')

    cols = list(all_rows[0].keys())
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(all_rows)
    print(f'wrote {SUMMARY} with {len(all_rows)} rows from {len(files)} cells')


if __name__ == '__main__':
    main()
