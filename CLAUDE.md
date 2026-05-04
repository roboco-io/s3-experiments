# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Nature

This is a **research repository**, not a deployable product. It probes the question "What else can S3 do?" by implementing five patterns (KV Store, Event Store, Litestream+SQLite, Serverless RDBMS, File I/O) and benchmarking them against the AWS service they would replace (DynamoDB, Kinesis, RDS, Aurora, EBS/EFS). Output is **data + writeups**, not libraries.

The README in three languages (`README.md` 한국어, `README.en.md`, `README.ja.md`) is the public-facing pitch. Treat the trilingual set as one document — changes to one usually require parallel changes to the other two.

## Repo Layout — What's Actually Here vs. What the README Describes

The README/PRD describe a planned monorepo under `patterns/<name>/` with `shared/` utilities and CDK Toolkit at the root. **That layout does not exist yet.** What's actually implemented:

```
docs/
├── PRD.md                          # Source of truth for design intent (read this first)
├── when-to-use.md
└── research/                       # Perplexity-driven research notes per pattern
    ├── SUMMARY.md                  # Index + cross-pattern findings
    ├── kv-store.md, event-sourcing.md, litestream-sqlite.md,
    ├── athena-rdbms.md, file-io.md, s3-tables-transactions.md
experiments/                        # The actual code lives here, one self-contained experiment per dir
├── kv-store-cost/                  # Python + matplotlib, local-only cost crossover charts
├── kv-store-listing/               # Python + boto3, hits real S3 (creates+destroys bucket)
├── event-notification/             # Python + boto3, creates S3+Lambda+DDB then tears down
├── s3-tables/                      # Python + boto3 + Athena
└── s3-tables-cdk/                  # TypeScript + CDK v2, the only CDK-based experiment
```

When asked to implement a "pattern," confirm whether the user wants it under `experiments/` (matches current convention) or wants you to scaffold the `patterns/` monorepo from the PRD. They are not the same thing.

## Per-Experiment Conventions

Every experiment is **independent**: own deps, own venv or `node_modules`, own `Makefile`, own `output/` (gitignored). There is no root build, no shared code, no cross-experiment imports. To work on an experiment, `cd` into it.

**Python experiments** (`kv-store-cost`, `kv-store-listing`, `event-notification`, `s3-tables`):
- `make` — full run (sets up `.venv/`, installs deps, executes `benchmark.py` or `chart.py`)
- `make clean` — wipe `.venv/` and `output/`
- venv path is local to each experiment — never assume a project-wide Python environment

**CDK experiment** (`s3-tables-cdk`):
- `make` (= `make deploy`) — runs `benchmark.sh`, which deploys → benchmarks → destroys in one shot. Generates a per-run `RUN_ID` to keep concurrent runs isolated.
- `make synth RUN_ID=<id>` / `make destroy RUN_ID=<id>` — manual control
- `make clean` — removes `dist/`, `output/`, `cdk.out/`
- Outputs land in `output/cdk-outputs.json`; `benchmark.ts` reads bucket/Glue/Athena names from there
- Uses `@aws-cdk/aws-s3tables-alpha` (still alpha) — version pinning matters

## Real-AWS Cost Discipline

Every experiment except `kv-store-cost` creates real AWS resources in **`us-east-1`** (S3 Tables GA region). Each Makefile prints an estimated cost and a 5-second cancel window before running. Two rules:

1. **Don't run experiments without checking the printed cost first.** They self-clean, but a botched run can leak resources.
2. **us-east-1 is fixed** for benchmark consistency — don't change region without updating the README's methodology section.

## Benchmark Methodology (from CONTRIBUTING.md and PRD)

When adding or modifying a benchmark, preserve these properties — they are load-bearing for the project's credibility:
- Minimum 100 iterations per metric, discard the first 10 as warmup
- Report p50/p95/p99 latencies (not just averages)
- Separate Lambda cold-start from warm invocations
- Cost numbers must cite the AWS price list date used

## TypeScript Style (for `s3-tables-cdk` and any future CDK work)

- TypeScript strict mode (already on in `tsconfig.json`)
- AWS CDK v2, AWS SDK v3 (`@aws-sdk/*`)
- Stacks must be `cdk destroy`-clean: `autoDeleteObjects: true`, `removalPolicy: DESTROY`
- IAM least-privilege scoped to specific bucket/table ARNs, not `*`

## Recent Trajectory (read git log for current state)

Recent commits center on **S3 Tables benchmarking** (`s3-tables-cdk`) — multiple runs documenting variance and pre-compaction slowdown vs regular Iceberg. The S3 Files benchmark design spec was added but not yet implemented. If asked about "current work," check `git log` rather than assuming the PRD's phase order.

## When the PRD and Reality Disagree

`docs/PRD.md` is aspirational (Phase 1 monorepo scaffolding, 5 patterns, etc.); `experiments/` is what exists. `docs/research/SUMMARY.md` documents findings that already invalidate parts of the PRD (e.g., "S3 is always cheaper" was found false for KV Store request costs; Event Store reframed from Kinesis-replacement to cold-archive). Trust SUMMARY.md over PRD.md for current thinking.
