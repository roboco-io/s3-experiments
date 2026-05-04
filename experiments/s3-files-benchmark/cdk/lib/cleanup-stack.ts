import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';

export interface CleanupStackProps extends cdk.StackProps {
  /** Stack names to delete, in deploy order (will be deleted in reverse). */
  targetStackNames: string[];
  /** Hours after the first target stack's creation before auto-delete fires. */
  thresholdHours?: number;
}

export class CleanupStack extends cdk.Stack {
  public readonly cleanupLambdaArn: string;
  public readonly cleanupLambda: lambda.Function;

  constructor(scope: Construct, id: string, props: CleanupStackProps) {
    super(scope, id, props);

    const thresholdHours = props.thresholdHours ?? 24;

    this.cleanupLambda = new lambda.Function(this, 'AutoDestroyFn', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      timeout: cdk.Duration.seconds(60),
      memorySize: 256,
      environment: {
        TARGET_STACKS: JSON.stringify(props.targetStackNames),
        THRESHOLD_HOURS: thresholdHours.toString(),
      },
      code: lambda.Code.fromInline(`
import os, json, datetime, logging
import boto3
log = logging.getLogger()
log.setLevel(logging.INFO)
cf = boto3.client('cloudformation')

def handler(event, context):
    targets = json.loads(os.environ['TARGET_STACKS'])
    threshold = int(os.environ.get('THRESHOLD_HOURS', '24'))
    forced = event.get('source') == 'manual' or event.get('forced') is True

    # Age check based on FIRST stack (network — created first, longest-lived)
    if not forced:
        try:
            r = cf.describe_stacks(StackName=targets[0])
            creation = r['Stacks'][0]['CreationTime']
            age_h = (datetime.datetime.now(datetime.timezone.utc) - creation).total_seconds() / 3600
            if age_h < threshold:
                log.info(f"{targets[0]} age {age_h:.2f}h < {threshold}h; skip")
                return {'skipped': True, 'age_hours': age_h}
        except cf.exceptions.ClientError as e:
            msg = str(e)
            if 'does not exist' in msg:
                log.info(f"{targets[0]} already deleted; nothing to do")
                return {'noop': True}
            raise

    # Delete in reverse order (client -> storage -> network)
    results = {}
    for s in reversed(targets):
        try:
            cf.delete_stack(StackName=s)
            log.info(f"delete_stack {s} initiated")
            results[s] = 'deleting'
        except cf.exceptions.ClientError as e:
            msg = str(e)
            if 'does not exist' in msg:
                results[s] = 'absent'
            else:
                results[s] = f'error: {msg}'
                log.warning(f"{s}: {msg}")
    return {'forced': forced, 'results': results}
`),
    });

    // Lambda only needs CFN delete perms — CFN itself uses deployment role to
    // delete underlying resources (CDK default deployment role has admin).
    this.cleanupLambda.addToRolePolicy(new iam.PolicyStatement({
      actions: ['cloudformation:DescribeStacks', 'cloudformation:DeleteStack'],
      resources: ['*'],
    }));

    // Hourly trigger; Lambda's age check makes it a no-op until 24h passes.
    new events.Rule(this, 'HourlyTick', {
      schedule: events.Schedule.rate(cdk.Duration.hours(1)),
      targets: [new targets.LambdaFunction(this.cleanupLambda)],
      description: `Auto-destroy after ${thresholdHours}h. Idempotent.`,
    });

    this.cleanupLambdaArn = this.cleanupLambda.functionArn;

    new cdk.CfnOutput(this, 'CleanupLambdaArn', { value: this.cleanupLambdaArn });
    new cdk.CfnOutput(this, 'ManualInvokeCmd', {
      value: `aws lambda invoke --function-name ${this.cleanupLambda.functionName} --cli-binary-format raw-in-base64-out --payload '{"forced":true}' /tmp/out.json --region ${this.region}`,
    });
  }
}
