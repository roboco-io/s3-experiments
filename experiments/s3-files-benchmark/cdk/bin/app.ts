#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { NetworkStack } from '../lib/network-stack';
import { StorageStack } from '../lib/storage-stack';
import { ClientStack } from '../lib/client-stack';
import { CleanupStack } from '../lib/cleanup-stack';
import { BudgetStack } from '../lib/budget-stack';

const app = new cdk.App();

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1',
};

const projectTag = app.node.tryGetContext('projectTag') ?? 's3-files-benchmark';
cdk.Tags.of(app).add('Project', projectTag);

const network = new NetworkStack(app, 'S3FilesBenchmark-Network', { env });

const storage = new StorageStack(app, 'S3FilesBenchmark-Storage', {
  env,
  vpc: network.vpc,
  nfsSecurityGroup: network.nfsSecurityGroup,
});

const client = new ClientStack(app, 'S3FilesBenchmark-Client', {
  env,
  vpc: network.vpc,
  nfsSecurityGroup: network.nfsSecurityGroup,
  bucketA: storage.bucketA,
  bucketB: storage.bucketB,
  s3FilesFileSystemId: storage.s3FilesFileSystemId,
  efsFileSystem: storage.efsFileSystem,
});

const cleanup = new CleanupStack(app, 'S3FilesBenchmark-Cleanup', {
  env,
  targetStackNames: [
    network.stackName,
    storage.stackName,
    client.stackName,
  ],
});

new BudgetStack(app, 'S3FilesBenchmark-Budget', {
  env,
  cleanupLambdaArn: cleanup.cleanupLambdaArn,
  dailyLimitUsd: 5,
});

app.synth();
