# Experiments

Each subdirectory contains an independent experiment with its own `Makefile`.

## Structure

```
experiments/
├── kv-store-cost/        # S3 vs DynamoDB cost crossover analysis
│   ├── chart.py          # Generates cost comparison charts
│   ├── Makefile          # make: setup venv, run, copy charts to docs/
│   └── output/           # Generated PNG charts
│
├── kv-store-listing/     # S3 ListObjectsV2 / GetObject performance benchmark
│   ├── benchmark.py      # Runs against real AWS S3 (creates/deletes bucket)
│   ├── Makefile          # make: setup venv, run benchmark
│   └── output/           # results.json
```

## Usage

```bash
# Run a specific experiment
cd experiments/kv-store-cost
make

# Run listing benchmark (requires AWS credentials, ~10 min)
cd experiments/kv-store-listing
make

# Clean up venv and outputs
make clean
```

## Notes

- Each experiment manages its own Python venv (`.venv/`)
- `kv-store-listing` creates real AWS resources — requires configured AWS credentials
- `kv-store-cost` is local-only (matplotlib charts)
