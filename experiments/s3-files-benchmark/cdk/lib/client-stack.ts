import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as efs from 'aws-cdk-lib/aws-efs';

export interface ClientStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
  nfsSecurityGroup: ec2.ISecurityGroup;
  bucketA: s3.IBucket;
  bucketB: s3.IBucket;
  s3FilesFileSystemId: string;
  efsFileSystem: efs.IFileSystem;
}

export class ClientStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ClientStackProps) {
    super(scope, id, props);
    // TODO: implement per spec section 5.1 (c6gn.xlarge Spot via LaunchTemplate)
    throw new Error('ClientStack not yet implemented');
  }
}
