import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';

export interface BudgetStackProps extends cdk.StackProps {
  cleanupLambdaArn: string;
  dailyLimitUsd: number;
}

export class BudgetStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: BudgetStackProps) {
    super(scope, id, props);
    // TODO: implement per spec section 5.4 (AWS Budgets + SNS + Lambda)
    throw new Error('BudgetStack not yet implemented');
  }
}
