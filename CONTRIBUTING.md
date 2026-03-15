# Contributing

We welcome contributions to S3 Experiments!

## How to Add a New Pattern

1. Create a new directory under `patterns/<pattern-name>/`
2. Include:
   - `README.md` — Architecture diagram (Mermaid), usage, tradeoffs
   - `lib/` — CDK stack
   - `src/` — Demo code
   - `benchmark/` — Performance & cost comparison script
   - `cdk.json` — CDK app config
3. Each pattern must be independently deployable via `cdk deploy`
4. Include `cdk destroy` cleanup (use `autoDeleteObjects: true`, `removalPolicy: DESTROY`)
5. Add IAM least-privilege policies

## How to Improve Benchmarks

- Run benchmarks in `us-east-1` for consistency
- Minimum 100 iterations, discard first 10 as warmup
- Report p50/p95/p99 latencies
- Separate cold/warm Lambda measurements

## Code Style

- TypeScript with strict mode
- AWS CDK v2
- AWS SDK v3 (`@aws-sdk/*`)

## Reporting Issues

Open an issue on GitHub with:
- What you expected
- What actually happened
- Steps to reproduce
