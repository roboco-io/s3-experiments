import {
  AthenaClient,
  StartQueryExecutionCommand,
  GetQueryExecutionCommand,
  QueryExecutionState,
} from '@aws-sdk/client-athena';
import * as fs from 'fs';

const REGION = 'us-east-1';
const athena = new AthenaClient({ region: REGION });

// Parse CLI args
function parseArgs(): Record<string, string> {
  const args: Record<string, string> = {};
  for (let i = 2; i < process.argv.length; i += 2) {
    const key = process.argv[i].replace('--', '');
    args[key] = process.argv[i + 1];
  }
  return args;
}

interface QueryResult {
  label: string;
  state: string;
  totalMs: number;
  engineMs: number;
  queueMs: number;
  planningMs: number;
  scannedBytes: number;
}

async function runQuery(
  sql: string,
  workgroup: string,
  outputLocation: string,
  database?: string,
  catalog?: string,
  label?: string,
): Promise<QueryResult | null> {
  const params: any = {
    QueryString: sql,
    WorkGroup: workgroup,
    ResultConfiguration: { OutputLocation: outputLocation },
  };
  if (database || catalog) {
    params.QueryExecutionContext = {};
    if (database) params.QueryExecutionContext.Database = database;
    if (catalog) params.QueryExecutionContext.Catalog = catalog;
  }

  const start = Date.now();
  const startResp = await athena.send(new StartQueryExecutionCommand(params));
  const queryId = startResp.QueryExecutionId!;

  // Poll for completion
  let execution: any;
  while (true) {
    const resp = await athena.send(
      new GetQueryExecutionCommand({ QueryExecutionId: queryId }),
    );
    execution = resp.QueryExecution!;
    const state = execution.Status!.State;
    if (
      state === QueryExecutionState.SUCCEEDED ||
      state === QueryExecutionState.FAILED ||
      state === QueryExecutionState.CANCELLED
    ) {
      break;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }

  const totalMs = Date.now() - start;
  const stats = execution.Statistics || {};
  const state = execution.Status!.State!;

  if (state === QueryExecutionState.FAILED) {
    const reason = execution.Status?.StateChangeReason || 'unknown';
    console.log(`    ${label || 'query'}: FAILED — ${reason}`);
    return null;
  }

  const result: QueryResult = {
    label: label || '',
    state,
    totalMs,
    engineMs: stats.EngineExecutionTimeInMillis || 0,
    queueMs: stats.QueryQueueTimeInMillis || 0,
    planningMs: stats.QueryPlanningTimeInMillis || 0,
    scannedBytes: stats.DataScannedInBytes || 0,
  };

  if (label) {
    console.log(
      `    ${label}: total=${totalMs}ms  engine=${result.engineMs}ms  ` +
        `queue=${result.queueMs}ms  plan=${result.planningMs}ms  ` +
        `scanned=${(result.scannedBytes / 1024 / 1024).toFixed(2)}MB`,
    );
  }
  return result;
}

async function insertData(
  tablePath: string,
  workgroup: string,
  outputLocation: string,
  database?: string,
  catalog?: string,
  rowCount: number = 1000,
) {
  console.log(`  Inserting ${rowCount} rows into ${tablePath}...`);
  const batchSize = 200;
  for (let batchStart = 0; batchStart < rowCount; batchStart += batchSize) {
    const batchEnd = Math.min(batchStart + batchSize, rowCount);
    const values: string[] = [];
    for (let i = batchStart; i < batchEnd; i++) {
      values.push(
        `('ord-${String(i).padStart(6, '0')}', 'cust-${String(i % 100).padStart(4, '0')}', ` +
          `'product-${i % 50}', ${(i % 10) + 1}, ` +
          `${(9.99 + (i % 100) * 0.5).toFixed(2)}, ` +
          `'2026-03-${String((i % 28) + 1).padStart(2, '0')}')`,
      );
    }
    await runQuery(
      `INSERT INTO ${tablePath} VALUES ${values.join(', ')}`,
      workgroup,
      outputLocation,
      database,
      catalog,
    );
  }
  console.log(`  done (${rowCount} rows)`);
}

interface BenchmarkSummary {
  query: string;
  coldTotalMs: number;
  coldEngineMs: number;
  warmAvgTotalMs: number;
  warmP50TotalMs: number;
  scannedMb: number;
}

async function benchmarkQueries(
  tablePath: string,
  workgroup: string,
  outputLocation: string,
  label: string,
  database?: string,
  catalog?: string,
  trials: number = 5,
): Promise<BenchmarkSummary[]> {
  console.log(`\n  === Benchmarking: ${label} ===`);

  const queries: [string, string][] = [
    ['COUNT(*)', `SELECT COUNT(*) FROM ${tablePath}`],
    ['WHERE filter', `SELECT * FROM ${tablePath} WHERE customer_id = 'cust-0042' LIMIT 10`],
    ['GROUP BY agg', `SELECT product, SUM(quantity), AVG(price) FROM ${tablePath} GROUP BY product`],
    ['ORDER BY', `SELECT * FROM ${tablePath} ORDER BY price DESC LIMIT 20`],
  ];

  const allResults: BenchmarkSummary[] = [];

  for (const [qLabel, sql] of queries) {
    console.log(`\n    [${qLabel}]`);
    const timings: QueryResult[] = [];

    for (let trial = 0; trial < trials; trial++) {
      const tag = trial === 0 ? 'COLD' : `warm-${trial}`;
      const result = await runQuery(sql, workgroup, outputLocation, database, catalog, tag);
      if (result) timings.push(result);
      if (trial === 0) await new Promise((r) => setTimeout(r, 2000));
    }

    if (timings.length > 0) {
      const cold = timings[0].totalMs;
      const warmTotals = timings.slice(1).map((t) => t.totalMs);
      const warmAvg = warmTotals.length
        ? Math.round(warmTotals.reduce((a, b) => a + b, 0) / warmTotals.length)
        : cold;
      const warmSorted = [...warmTotals].sort((a, b) => a - b);
      const warmP50 = warmSorted.length
        ? warmSorted[Math.floor(warmSorted.length / 2)]
        : cold;

      const summary: BenchmarkSummary = {
        query: qLabel,
        coldTotalMs: cold,
        coldEngineMs: timings[0].engineMs,
        warmAvgTotalMs: warmAvg,
        warmP50TotalMs: warmP50,
        scannedMb: Number((timings[0].scannedBytes / 1024 / 1024).toFixed(2)),
      };
      allResults.push(summary);
      console.log(
        `    Summary: cold=${cold}ms  warm_avg=${warmAvg}ms  warm_p50=${warmP50}ms`,
      );
    }
  }
  return allResults;
}

async function main() {
  const args = parseArgs();
  const {
    tableBucket,
    regularBucket,
    glueDb,
    workgroup,
    athenaOutput,
    runId,
  } = args;

  const results: any = {
    runId,
    region: REGION,
    timestamp: new Date().toISOString(),
    experiments: {} as Record<string, BenchmarkSummary[]>,
  };

  // ============================================================
  // Phase A: Regular S3 + Iceberg baseline
  // ============================================================
  console.log('\n--- Regular S3 + Iceberg Baseline ---');

  // Create Iceberg table
  console.log('  Creating Iceberg table via Athena...');
  await runQuery(
    `CREATE TABLE ${glueDb}.orders (
      order_id STRING, customer_id STRING, product STRING,
      quantity INT, price DOUBLE, order_date STRING
    ) LOCATION 's3://${regularBucket}/iceberg/orders/'
    TBLPROPERTIES ('table_type' = 'ICEBERG')`,
    workgroup,
    athenaOutput,
    glueDb,
    undefined,
    'CREATE TABLE',
  );

  await insertData(`${glueDb}.orders`, workgroup, athenaOutput, glueDb);
  results.experiments.regular_iceberg = await benchmarkQueries(
    `${glueDb}.orders`,
    workgroup,
    athenaOutput,
    'Regular S3 + Iceberg',
    glueDb,
  );

  // ============================================================
  // Phase B: S3 Tables via catalog
  // ============================================================
  console.log('\n--- S3 Tables ---');

  // S3 Tables catalog name: s3tablescatalog/<bucket-name>
  const s3TablesCatalog = `s3tablescatalog/${tableBucket}`;
  const s3TablesPath = `"${s3TablesCatalog}"."benchmark"."orders"`;

  console.log(`  S3 Tables catalog: ${s3TablesCatalog}`);
  console.log(`  Table path: ${s3TablesPath}`);

  // Try to query the S3 Tables table
  console.log('  Checking table access...');
  const checkResult = await runQuery(
    `SELECT 1 FROM ${s3TablesPath} LIMIT 1`,
    workgroup,
    athenaOutput,
    'benchmark',
    s3TablesCatalog,
    'access check',
  );

  if (checkResult && checkResult.state === 'SUCCEEDED') {
    console.log('  Table accessible!');
    await insertData(
      `"benchmark"."orders"`,
      workgroup,
      athenaOutput,
      'benchmark',
      s3TablesCatalog,
    );
    results.experiments.s3_tables = await benchmarkQueries(
      `"benchmark"."orders"`,
      workgroup,
      athenaOutput,
      'S3 Tables',
      'benchmark',
      s3TablesCatalog,
    );
  } else {
    console.log('  S3 Tables not accessible via Athena.');
    console.log('  This likely requires Lake Formation integration (manual console setup).');
    console.log('  Skipping S3 Tables benchmark — using research estimates instead.');
  }

  // ============================================================
  // Summary
  // ============================================================
  console.log('\n' + '='.repeat(70));
  console.log('SUMMARY');
  console.log('='.repeat(70));

  for (const [expName, expResults] of Object.entries(results.experiments) as [string, BenchmarkSummary[]][]) {
    console.log(`\n  [${expName}]`);
    console.log(
      `  ${'Query'.padEnd(20)} ${'Cold(ms)'.padStart(10)} ${'WarmAvg'.padStart(10)} ${'WarmP50'.padStart(10)} ${'Scanned'.padStart(10)}`,
    );
    console.log(`  ${'─'.repeat(20)} ${'─'.repeat(10)} ${'─'.repeat(10)} ${'─'.repeat(10)} ${'─'.repeat(10)}`);
    for (const r of expResults) {
      console.log(
        `  ${r.query.padEnd(20)} ${String(r.coldTotalMs).padStart(10)} ${String(r.warmAvgTotalMs).padStart(10)} ${String(r.warmP50TotalMs).padStart(10)} ${(r.scannedMb + 'MB').padStart(10)}`,
      );
    }
  }

  // Comparison
  if (results.experiments.regular_iceberg && results.experiments.s3_tables) {
    console.log('\n  [Comparison: S3 Tables vs Regular Iceberg]');
    const reg = Object.fromEntries(
      results.experiments.regular_iceberg.map((r: BenchmarkSummary) => [r.query, r]),
    );
    const tab = Object.fromEntries(
      results.experiments.s3_tables.map((r: BenchmarkSummary) => [r.query, r]),
    );
    for (const q of Object.keys(reg)) {
      if (tab[q]) {
        const coldSpeedup = reg[q].coldTotalMs / Math.max(1, tab[q].coldTotalMs);
        const warmSpeedup = reg[q].warmAvgTotalMs / Math.max(1, tab[q].warmAvgTotalMs);
        console.log(`  ${q.padEnd(20)}  cold: ${coldSpeedup.toFixed(1)}x  warm: ${warmSpeedup.toFixed(1)}x`);
      }
    }
  }

  // Save results
  fs.mkdirSync('output', { recursive: true });
  fs.writeFileSync('output/results.json', JSON.stringify(results, null, 2));
  console.log('\nResults saved to output/results.json');
}

main().catch(console.error);
