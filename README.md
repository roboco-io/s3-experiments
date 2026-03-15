# S3 Experiments — What Else Can S3 Do?

**English** | [한국어](./README.ko.md) | [日本語](./README.ja.md)

> What if S3 isn't just storage? Explore S3 as a **Key-Value Store**, **Event Store**, **Durable RDBMS (Litestream+SQLite)**, **Serverless RDBMS (Athena)**, and **File I/O Alternative** — with working code, CDK deployments, and honest benchmarks against dedicated AWS services.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-blue.svg)](https://www.typescriptlang.org/)
[![AWS CDK](https://img.shields.io/badge/AWS_CDK-v2-orange.svg)](https://aws.amazon.com/cdk/)

## Why S3?

Amazon S3 is often seen as "just a place to put files." But with **$0.023/GB storage**, **11 nines of durability**, **zero servers to manage**, and **infinite scalability**, S3 is quietly one of the most powerful primitives in AWS.

This project explores what happens when you push S3 beyond its traditional role:

| What You Get | What It Costs |
|---|---|
| Zero provisioned capacity | Pay only for what you use |
| No servers, clusters, or patches | IAM policies = your entire security config |
| Automatic scaling to any load | No capacity planning needed |
| 99.999999999% durability | Sleep well at night |

**This is NOT a claim that S3 replaces dedicated services.** Each pattern includes honest tradeoff analysis showing exactly when S3 makes sense and when you should use DynamoDB, RDS, or Aurora instead.

## Patterns

| # | Pattern | Replaces | Key Insight | Status |
|---|---------|----------|-------------|--------|
| 1 | [**Key-Value Store**](./patterns/kv-store/) | DynamoDB | S3 object key = your key, object body = your value. Can it handle 500K keys cost-effectively? | 🔲 |
| 2 | [**S3 as Event Store**](./patterns/event-sourcing/) | Kinesis / SQS | S3 Event Notifications as a durable, replayable event log. | 🔲 |
| 3 | [**Litestream + SQLite**](./patterns/litestream-sqlite/) | RDS (small) | In-memory DB speed + S3 durability via [Litestream](https://github.com/benbjohnson/litestream). Fargate Spot RTO/RPO experiment. | 🔲 |
| 4 | [**Serverless RDBMS**](./patterns/serverless-rdbms/) | RDS / Aurora | Parquet on S3 + Athena = SQL queries without a database server. If you can tolerate seconds, why pay for RDS? | 🔲 |
| 5 | [**S3 as File I/O**](./patterns/s3-file-io/) | EBS / EFS | How does S3 API read/write compare to local filesystem? File-size-dependent performance profiling. | 🔲 |

Each pattern is **independently deployable** — pick the one you care about and deploy it in under 10 minutes.

## Quick Start

### Prerequisites

- Node.js 20+
- AWS CLI configured with credentials
- AWS CDK v2 (`npm install -g aws-cdk`)

### Deploy a Pattern

```bash
# Clone the repo
git clone https://github.com/roboco-io/s3-experiments.git
cd s3-experiments

# Install dependencies
npm install

# Pick a pattern and deploy
cd patterns/kv-store
npx cdk deploy

# Run the demo
npx tsx src/demo.ts

# Run the benchmark
npm run benchmark

# Clean up (all resources removed)
npx cdk destroy
```

## Project Structure

```
s3-experiments/
├── README.md                          # You are here
├── patterns/
│   ├── kv-store/                      # Pattern 1: S3 as Key-Value Store
│   │   ├── README.md                  #   Architecture, usage, tradeoffs
│   │   ├── lib/                       #   CDK stack
│   │   ├── src/                       #   Demo code & Lambda handlers
│   │   └── benchmark/                 #   Performance & cost comparison
│   ├── event-sourcing/                # Pattern 2: S3 as Event Store
│   ├── litestream-sqlite/             # Pattern 3: Litestream + SQLite + Fargate
│   ├── serverless-rdbms/             # Pattern 4: S3 + Athena RDBMS
│   └── s3-file-io/                    # Pattern 5: S3 API vs Filesystem
├── shared/                            # Common utilities (S3 client, cost calculator)
├── docs/
│   ├── architecture.md                # Architecture philosophy
│   ├── cost-comparison.md             # Consolidated cost comparison
│   └── when-to-use.md                 # Decision guide
└── CONTRIBUTING.md                    # How to add new patterns
```

## Benchmarks

Every pattern includes a benchmark comparing S3-based implementation against the dedicated AWS service it replaces.

| Pattern | Metrics | Compared Against |
|---------|---------|-----------------|
| KV Store | Latency (p50/p95/p99), throughput, cost/1M ops (10K~500K keys) | DynamoDB on-demand (actually deployed) |
| Event Store | Write latency, projection delay, cost/1M events | Kinesis Data Streams (published pricing) |
| Litestream+SQLite | RTO, RPO, query latency, monthly cost (On-Demand vs Spot) | RDS db.t4g.micro (actually deployed) |
| Serverless RDBMS | Query latency by complexity (1MB~10GB), scan cost, cost/1K queries | Aurora Serverless v2 (published pricing) |
| S3 File I/O | Read/write latency by file size (1KB~1GB), throughput (MB/s), concurrent IOPS | EBS gp3 + EFS (actually deployed) |

**Methodology:** 100+ iterations per metric, first 10 discarded as warmup, cold/warm Lambda latencies reported separately. All benchmarks run in `us-east-1`. See each pattern's `benchmark/results.md` for full details.

## When to Use S3 Patterns

S3-based patterns shine when:
- **Cost sensitivity** — You need storage/compute at the lowest possible price
- **Low-to-moderate traffic** — Hundreds to thousands of requests/minute, not millions
- **Simplicity** — You want zero infrastructure to manage
- **Durability matters more than latency** — Archive, audit logs, event history

Use dedicated services when:
- **Sub-millisecond latency** — DynamoDB, ElastiCache are purpose-built for this
- **Complex transactions** — ACID guarantees across multiple operations
- **High-frequency reads** — S3 has per-prefix request limits
- **Real-time streaming** — Kinesis/SQS offer better guarantees

See [docs/when-to-use.md](./docs/when-to-use.md) for detailed decision guidance.

## Tech Stack

- **Runtime:** Node.js 20+ / TypeScript 5+
- **IaC:** AWS CDK v2
- **AWS SDK:** @aws-sdk/* v3
- **Testing:** Vitest
- **Package Manager:** npm workspaces

## Contributing

We welcome contributions! See [CONTRIBUTING.md](./CONTRIBUTING.md) for how to:
- Add a new S3 pattern
- Improve existing benchmarks
- Fix documentation

## License

MIT License. See [LICENSE](./LICENSE).

---

Built with the conviction that **the best infrastructure is the one you don't have to manage.**
