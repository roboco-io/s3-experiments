import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as efs from 'aws-cdk-lib/aws-efs';

export interface StorageStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
  nfsSecurityGroup: ec2.ISecurityGroup;
}

export class StorageStack extends cdk.Stack {
  public readonly bucketA: s3.Bucket;
  public readonly bucketB: s3.Bucket;
  public readonly s3FilesFileSystemId: string;
  public readonly efsFileSystem: efs.FileSystem;

  constructor(scope: Construct, id: string, props: StorageStackProps) {
    super(scope, id, props);
    // TODO: implement per spec section 5.1 + Amendment 1 (split buckets, S3 Files, EFS)
    throw new Error('StorageStack not yet implemented');
  }
}
