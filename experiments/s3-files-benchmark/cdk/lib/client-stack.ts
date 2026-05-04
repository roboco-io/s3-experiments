import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as efs from 'aws-cdk-lib/aws-efs';
import * as iam from 'aws-cdk-lib/aws-iam';

export interface ClientStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
  nfsSecurityGroup: ec2.ISecurityGroup;
  clientSecurityGroup?: ec2.ISecurityGroup;
  bucketA: s3.IBucket;
  bucketB: s3.IBucket;
  s3FilesFileSystemId: string;
  efsFileSystem: efs.IFileSystem;
  spotMaxPriceUsdPerHour?: number;
}

export class ClientStack extends cdk.Stack {
  public readonly launchTemplate: ec2.LaunchTemplate;
  public readonly instanceRole: iam.Role;

  constructor(scope: Construct, id: string, props: ClientStackProps) {
    super(scope, id, props);

    const subnet = props.vpc.publicSubnets[0];
    const region = cdk.Stack.of(this).region;

    // ── IAM role for EC2 instance profile ────────────────────────────────
    this.instanceRole = new iam.Role(this, 'ClientRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'),
      ],
    });
    props.bucketA.grantReadWrite(this.instanceRole);
    props.bucketB.grantReadWrite(this.instanceRole);

    // S3 Files mount permissions (scoped to this filesystem)
    this.instanceRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        's3files:DescribeMountTargets',
        's3files:GetFileSystem',
        's3files:GetMountTarget',
        's3files:ListMountTargets',
        's3files:ListFileSystems',
        's3files:ClientMount',
        's3files:ClientRootAccess',
        's3files:ClientWrite',
      ],
      resources: [
        `arn:aws:s3files:${region}:${this.account}:file-system/${props.s3FilesFileSystemId}`,
      ],
    }));

    // EFS client perms (not strictly required when SG is open, but explicit is better)
    this.instanceRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'elasticfilesystem:ClientMount',
        'elasticfilesystem:ClientRootAccess',
        'elasticfilesystem:ClientWrite',
        'elasticfilesystem:DescribeMountTargets',
      ],
      resources: [props.efsFileSystem.fileSystemArn],
    }));

    // CloudWatch logs (optional but useful for debugging UserData)
    this.instanceRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'logs:CreateLogGroup',
        'logs:CreateLogStream',
        'logs:PutLogEvents',
      ],
      resources: ['*'],
    }));

    // ── UserData ─────────────────────────────────────────────────────────
    // Installs packages, creates mount points, mounts three filesystems.
    // Script delivery (scripts/, fio/) is handled by a separate `make seed`
    // step that uploads a tarball to bucketA/scripts/ and SSM-runs setup.
    const userData = ec2.UserData.forLinux({ shebang: '#!/bin/bash' });
    userData.addCommands(
      'set -euxo pipefail',
      'exec > >(tee /var/log/userdata.log | logger -t userdata -s 2>/dev/console) 2>&1',
      'echo "[userdata] start $(date -u +%FT%TZ)"',

      // Update + base packages
      'dnf -y update',
      'dnf -y install fio sysstat jq amazon-efs-utils unzip',

      // mount-s3 (Mountpoint for S3) for AL2023 aarch64
      'curl -fsSLo /tmp/mount-s3.rpm https://s3.amazonaws.com/mountpoint-s3-release/latest/arm64/mount-s3.rpm',
      'dnf -y install /tmp/mount-s3.rpm',

      // Mount points
      'mkdir -p /mnt/s3files /mnt/mountpoint /mnt/efs',

      // Mount EFS
      `EFS_ID=${props.efsFileSystem.fileSystemId}`,
      'mount -t efs -o tls "$EFS_ID":/ /mnt/efs || echo "[userdata] efs mount failed (will retry via scripts)"',

      // Mount S3 Files (uses amazon-efs-utils which now ships s3files type)
      `S3FILES_ID=${props.s3FilesFileSystemId}`,
      'mount -t s3files "$S3FILES_ID":/ /mnt/s3files || echo "[userdata] s3files mount failed (will retry via scripts)"',

      // Mount Mountpoint for S3 (no cache for fairness)
      `BUCKET_B=${props.bucketB.bucketName}`,
      'mount-s3 "$BUCKET_B" /mnt/mountpoint --no-cache --allow-other || echo "[userdata] mountpoint mount failed (will retry via scripts)"',

      // Record mount table for diagnostics
      'mount | grep -E "s3files|mountpoint|efs" > /var/log/s3files-bench-mounts.log || true',

      // TODO (PHASE 2): pull scripts/ and fio/ from bucketA/_deploy/ and run scripts/50_run_all.sh
      // For now, leave the instance idle so SSM can be used to bootstrap manually.
      'echo "[userdata] mounts attempted. Awaiting SSM trigger of 50_run_all.sh"',
    );

    // ── LaunchTemplate with Spot ─────────────────────────────────────────
    const ami = ec2.MachineImage.fromSsmParameter(
      '/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64',
      { os: ec2.OperatingSystemType.LINUX }
    );

    const clientSg = props.clientSecurityGroup ?? props.nfsSecurityGroup;
    const spotMaxPrice = (props.spotMaxPriceUsdPerHour ?? 0.06).toString();

    this.launchTemplate = new ec2.LaunchTemplate(this, 'ClientLT', {
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.C6GN, ec2.InstanceSize.XLARGE),
      machineImage: ami,
      role: this.instanceRole,
      securityGroup: clientSg as ec2.SecurityGroup,
      userData,
      requireImdsv2: true,
      spotOptions: {
        requestType: ec2.SpotRequestType.ONE_TIME,
        maxPrice: Number(spotMaxPrice),
        interruptionBehavior: ec2.SpotInstanceInterruption.TERMINATE,
      },
      blockDevices: [
        {
          deviceName: '/dev/xvda',
          volume: ec2.BlockDeviceVolume.ebs(40, {
            volumeType: ec2.EbsDeviceVolumeType.GP3,
            deleteOnTermination: true,
          }),
        },
      ],
    });

    // Single Spot instance via CfnInstance (simplest for one-off experiment)
    const instance = new ec2.CfnInstance(this, 'ClientInstance', {
      launchTemplate: {
        launchTemplateId: this.launchTemplate.launchTemplateId,
        version: this.launchTemplate.latestVersionNumber,
      },
      subnetId: subnet.subnetId,
      tags: [
        { key: 'Name', value: 's3-files-benchmark-client' },
        { key: 'Project', value: 's3-files-benchmark' },
      ],
    });

    new cdk.CfnOutput(this, 'InstanceId', { value: instance.ref });
    new cdk.CfnOutput(this, 'InstanceRoleArn', { value: this.instanceRole.roleArn });
    new cdk.CfnOutput(this, 'LaunchTemplateId', {
      value: this.launchTemplate.launchTemplateId ?? '',
    });
  }
}
