import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as efs from 'aws-cdk-lib/aws-efs';
import * as iam from 'aws-cdk-lib/aws-iam';

export interface StorageStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
  nfsSecurityGroup: ec2.ISecurityGroup;
}

export class StorageStack extends cdk.Stack {
  public readonly bucketA: s3.Bucket;
  public readonly bucketB: s3.Bucket;
  public readonly s3FilesFileSystemId: string;
  public readonly s3FilesMountTargetId: string;
  public readonly efsFileSystem: efs.FileSystem;

  constructor(scope: Construct, id: string, props: StorageStackProps) {
    super(scope, id, props);

    const subnet = props.vpc.publicSubnets[0];

    // ── Buckets ──────────────────────────────────────────────────────────
    // A: backing store for S3 Files filesystem (versioning REQUIRED by S3 Files)
    // B: target for Mountpoint for S3 (direct mount, no S3 Files in front)
    this.bucketA = new s3.Bucket(this, 'BucketA', {
      bucketName: `s3files-bench-${this.account}-a`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true,
    });
    this.bucketB = new s3.Bucket(this, 'BucketB', {
      bucketName: `s3files-bench-${this.account}-b`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
    });

    // ── S3 Files service role ────────────────────────────────────────────
    // Live test 2026-05-04: IAM rejects 's3files.amazonaws.com' as unknown
    // service. Verified working principal is 's3.amazonaws.com' with a
    // SourceAccount condition (then s3files create-file-system succeeds).
    // Permissions: full R/W on bucketA + bucket notification config (sync events).
    const s3FilesServiceRole = new iam.Role(this, 'S3FilesServiceRole', {
      assumedBy: new iam.ServicePrincipal('s3.amazonaws.com', {
        conditions: { StringEquals: { 'aws:SourceAccount': this.account } },
      }),
      description: 'S3 Files service access to bucketA (S3 Files trust)',
    });
    this.bucketA.grantReadWrite(s3FilesServiceRole);
    s3FilesServiceRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        's3:GetBucketLocation',
        's3:GetBucketAcl',
        's3:PutBucketNotification',
        's3:GetBucketNotification',
      ],
      resources: [this.bucketA.bucketArn],
    }));

    // ── S3 Files filesystem (L1 — no L2 in aws-cdk-lib 2.252.0) ──────────
    // Per AWS::S3Files::FileSystem CFN schema (verified via describe-type).
    const s3FilesFs = new cdk.CfnResource(this, 'S3FilesFileSystem', {
      type: 'AWS::S3Files::FileSystem',
      properties: {
        Bucket: this.bucketA.bucketArn,
        RoleArn: s3FilesServiceRole.roleArn,
        AcceptBucketWarning: true,
        SynchronizationConfiguration: {
          ImportDataRules: [
            {
              Prefix: '',
              Trigger: 'ON_DIRECTORY_FIRST_ACCESS',
              SizeLessThan: 1073741824, // 1 GiB
            },
          ],
          ExpirationDataRules: [
            { DaysAfterLastAccess: 30 },
          ],
        },
        Tags: [
          { Key: 'Project', Value: 's3-files-benchmark' },
          { Key: 'Component', Value: 'S3FilesFileSystem' },
        ],
      },
    });
    s3FilesFs.applyRemovalPolicy(cdk.RemovalPolicy.DESTROY);
    s3FilesFs.node.addDependency(this.bucketA);

    this.s3FilesFileSystemId = s3FilesFs.getAtt('FileSystemId').toString();

    // ── S3 Files MountTarget in the single AZ ────────────────────────────
    const s3FilesMt = new cdk.CfnResource(this, 'S3FilesMountTarget', {
      type: 'AWS::S3Files::MountTarget',
      properties: {
        FileSystemId: this.s3FilesFileSystemId,
        SubnetId: subnet.subnetId,
        SecurityGroups: [props.nfsSecurityGroup.securityGroupId],
      },
    });
    s3FilesMt.applyRemovalPolicy(cdk.RemovalPolicy.DESTROY);
    s3FilesMt.node.addDependency(s3FilesFs);
    this.s3FilesMountTargetId = s3FilesMt.getAtt('MountTargetId').toString();

    // ── EFS Standard (baseline comparator) ───────────────────────────────
    this.efsFileSystem = new efs.FileSystem(this, 'EfsBaseline', {
      vpc: props.vpc,
      vpcSubnets: { subnets: [subnet] },
      securityGroup: props.nfsSecurityGroup as ec2.SecurityGroup,
      performanceMode: efs.PerformanceMode.GENERAL_PURPOSE,
      throughputMode: efs.ThroughputMode.BURSTING,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      encrypted: true,
    });

    // ── Outputs ──────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'BucketAName', { value: this.bucketA.bucketName });
    new cdk.CfnOutput(this, 'BucketBName', { value: this.bucketB.bucketName });
    new cdk.CfnOutput(this, 'S3FilesFileSystemIdOut', { value: this.s3FilesFileSystemId });
    new cdk.CfnOutput(this, 'S3FilesMountTargetIdOut', { value: this.s3FilesMountTargetId });
    new cdk.CfnOutput(this, 'EfsFileSystemIdOut', { value: this.efsFileSystem.fileSystemId });
  }
}
