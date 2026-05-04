# Repository Guidelines

## Project Structure & Module Organization

This repository is a research and benchmark collection for S3-based patterns. Root `README*.md` files provide localized overviews. `docs/` contains product notes, specs, and research writeups; `docs/research/` also holds generated charts. Experiments live under `experiments/<experiment-name>/` and are independently runnable. Most include a `Makefile`, a benchmark or chart script, and generated `output/` artifacts. The CDK benchmark is in `experiments/s3-tables-cdk/`, with TypeScript sources under `lib/`.

## Build, Test, and Development Commands

- `cd experiments/kv-store-cost && make`: generate cost charts and copy them into `docs/research/`.
- `cd experiments/kv-store-listing && make`: run the S3 listing benchmark against real AWS resources.
- `cd experiments/event-notification && make`: run the S3 event notification benchmark with temporary AWS resources.
- `cd experiments/s3-tables && make`: run the Python S3 Tables versus regular Iceberg benchmark.
- `cd experiments/s3-tables-cdk && npm install && make synth`: install CDK dependencies and synthesize the stack.
- `cd experiments/s3-tables-cdk && make benchmark`: deploy and run the CDK benchmark flow.
- `make clean`: remove local venvs and generated output in an experiment directory.

## Coding Style & Naming Conventions

Use Markdown for research documents, with descriptive lowercase-hyphen filenames such as `docs/research/file-io.md`. Keep benchmark directories lowercase and hyphenated. Python scripts use 4-space indentation. TypeScript CDK code should stay in strict-mode style, use AWS CDK v2, and prefer AWS SDK v3 packages from `@aws-sdk/*`.

## Testing Guidelines

There is no central test suite. Validate changes by running the relevant experiment `make` target or, for documentation-only edits, checking links and artifact paths. Benchmarks should run in `us-east-1` when AWS behavior is compared, use at least 100 iterations, discard warmup samples when applicable, and report p50/p95/p99 latency.

## Commit & Pull Request Guidelines

Recent commits use short, imperative summaries such as `Add S3 Files benchmark design spec` and `Fix broken links: add LICENSE, CONTRIBUTING, when-to-use docs`. Follow that style and mention benchmark run numbers or major findings when relevant. Pull requests should include affected docs or experiments, AWS resources created, cleanup behavior, estimated cost, and screenshots or chart diffs when visual outputs change.

## Security & Configuration Tips

Several experiments create real AWS resources. Use a sandbox AWS account or limited credentials, confirm the target region, and run cleanup such as `make clean` or `make destroy` for CDK stacks. Do not commit credentials, `.venv/`, `cdk.out/`, or experiment `output/` unless the artifact is intentionally copied into `docs/research/`.
