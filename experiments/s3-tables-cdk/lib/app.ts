#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { S3TablesBenchmarkStack } from './s3-tables-stack';

const app = new cdk.App();
const runId = process.env.RUN_ID || 'bench';

new S3TablesBenchmarkStack(app, 'S3TablesBenchmark', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: 'us-east-1',
  },
});

app.synth();
