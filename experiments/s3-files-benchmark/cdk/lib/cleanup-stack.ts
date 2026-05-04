import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';

export interface CleanupStackProps extends cdk.StackProps {
  targetStackNames: string[];
}

export class CleanupStack extends cdk.Stack {
  public readonly cleanupLambdaArn: string;

  constructor(scope: Construct, id: string, props: CleanupStackProps) {
    super(scope, id, props);
    // TODO: implement per spec section 5.2 (24h auto-destroy Lambda + EventBridge)
    throw new Error('CleanupStack not yet implemented');
  }
}
