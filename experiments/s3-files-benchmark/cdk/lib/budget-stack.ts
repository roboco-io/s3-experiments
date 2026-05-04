import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as snsSub from 'aws-cdk-lib/aws-sns-subscriptions';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';

export interface BudgetStackProps extends cdk.StackProps {
  cleanupLambdaArn: string;
  /** Daily USD limit. Actual spend exceeding this fires the cleanup. */
  dailyLimitUsd: number;
}

export class BudgetStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: BudgetStackProps) {
    super(scope, id, props);

    // SNS topic that AWS Budgets will publish to.
    const topic = new sns.Topic(this, 'BudgetAlertTopic', {
      displayName: 's3-files-benchmark budget alarm',
    });
    // Budgets service must be allowed to publish.
    topic.addToResourcePolicy(new iam.PolicyStatement({
      principals: [new iam.ServicePrincipal('budgets.amazonaws.com')],
      actions: ['SNS:Publish'],
      resources: [topic.topicArn],
    }));

    // Lambda that invokes the cleanup function with forced=true on alarm.
    const trigger = new lambda.Function(this, 'BudgetTriggerFn', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      timeout: cdk.Duration.seconds(30),
      environment: { CLEANUP_LAMBDA_ARN: props.cleanupLambdaArn },
      code: lambda.Code.fromInline(`
import os, json, logging
import boto3
log = logging.getLogger()
log.setLevel(logging.INFO)
client = boto3.client('lambda')

def handler(event, context):
    arn = os.environ['CLEANUP_LAMBDA_ARN']
    log.info(f"Budget alarm received: {json.dumps(event)[:500]}")
    resp = client.invoke(
        FunctionName=arn,
        InvocationType='Event',  # async fire-and-forget
        Payload=json.dumps({'forced': True, 'reason': 'budget-alarm'}).encode(),
    )
    log.info(f"cleanup invoke status={resp['StatusCode']}")
    return {'invoked': arn}
`),
    });
    trigger.addToRolePolicy(new iam.PolicyStatement({
      actions: ['lambda:InvokeFunction'],
      resources: [props.cleanupLambdaArn],
    }));

    topic.addSubscription(new snsSub.LambdaSubscription(trigger));

    // Daily budget — actual cost; alarm at 100% triggers SNS → trigger lambda.
    new budgets.CfnBudget(this, 'DailyBudget', {
      budget: {
        budgetName: `s3-files-benchmark-daily-${this.stackName}`,
        budgetType: 'COST',
        timeUnit: 'DAILY',
        budgetLimit: { amount: props.dailyLimitUsd, unit: 'USD' },
        costFilters: { TagKeyValue: ['user:Project$s3-files-benchmark'] },
      },
      notificationsWithSubscribers: [
        {
          notification: {
            notificationType: 'ACTUAL',
            comparisonOperator: 'GREATER_THAN',
            threshold: 100,
            thresholdType: 'PERCENTAGE',
          },
          subscribers: [
            { subscriptionType: 'SNS', address: topic.topicArn },
          ],
        },
      ],
    });

    new cdk.CfnOutput(this, 'BudgetTopicArn', { value: topic.topicArn });
    new cdk.CfnOutput(this, 'BudgetTriggerFnArn', { value: trigger.functionArn });
  }
}
