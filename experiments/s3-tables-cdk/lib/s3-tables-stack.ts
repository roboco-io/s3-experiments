import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as glue from 'aws-cdk-lib/aws-glue';
import * as athena from 'aws-cdk-lib/aws-athena';
import * as s3tables from '@aws-cdk/aws-s3tables-alpha';
import { Construct } from 'constructs';

export class S3TablesBenchmarkStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const runId = this.node.tryGetContext('runId') || 'bench';

    // ============================================================
    // 1. S3 Tables (Table Bucket + Namespace + Table)
    // ============================================================
    const tableBucket = new s3tables.TableBucket(this, 'TableBucket', {
      tableBucketName: `s3dd-tbench-${runId}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const namespace = new s3tables.Namespace(this, 'BenchNamespace', {
      namespaceName: 'benchmark',
      tableBucket: tableBucket,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const ordersTable = new s3tables.Table(this, 'OrdersTable', {
      tableName: 'orders',
      namespace: namespace,
      openTableFormat: s3tables.OpenTableFormat.ICEBERG,
      withoutMetadata: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ============================================================
    // 2. Regular S3 + Glue Iceberg (comparison baseline)
    // ============================================================
    const regularBucket = new s3.Bucket(this, 'RegularBucket', {
      bucketName: `s3dd-rbench-${runId}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    const glueDb = new glue.CfnDatabase(this, 'GlueDatabase', {
      catalogId: this.account,
      databaseInput: {
        name: `s3dd_bench_${runId.replace(/-/g, '_')}`,
        description: 'S3 Tables benchmark - regular Iceberg baseline',
      },
    });

    // ============================================================
    // 3. Athena Workgroup + Output Bucket
    // ============================================================
    const athenaOutputBucket = new s3.Bucket(this, 'AthenaOutputBucket', {
      bucketName: `s3dd-athena-${runId}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    const workgroup = new athena.CfnWorkGroup(this, 'BenchWorkgroup', {
      name: `s3dd-bench-${runId}`,
      state: 'ENABLED',
      workGroupConfiguration: {
        resultConfiguration: {
          outputLocation: `s3://${athenaOutputBucket.bucketName}/results/`,
        },
        engineVersion: {
          selectedEngineVersion: 'Athena engine version 3',
        },
      },
    });

    // ============================================================
    // Outputs
    // ============================================================
    new cdk.CfnOutput(this, 'TableBucketArn', {
      value: tableBucket.tableBucketArn,
      description: 'S3 Table Bucket ARN',
    });

    new cdk.CfnOutput(this, 'TableBucketName', {
      value: tableBucket.tableBucketName,
      description: 'S3 Table Bucket Name',
    });

    new cdk.CfnOutput(this, 'RegularBucketName', {
      value: regularBucket.bucketName,
      description: 'Regular S3 Bucket Name',
    });

    new cdk.CfnOutput(this, 'GlueDatabaseName', {
      value: `s3dd_bench_${runId.replace(/-/g, '_')}`,
      description: 'Glue Database Name',
    });

    new cdk.CfnOutput(this, 'AthenaWorkgroup', {
      value: workgroup.name,
      description: 'Athena Workgroup Name',
    });

    new cdk.CfnOutput(this, 'AthenaOutputLocation', {
      value: `s3://${athenaOutputBucket.bucketName}/results/`,
      description: 'Athena Output Location',
    });
  }
}
