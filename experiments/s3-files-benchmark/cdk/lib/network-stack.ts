import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';

export interface NetworkStackProps extends cdk.StackProps {
  /** Explicit AZ list to avoid CDK context lookup (prevents wrong-region cache). */
  availabilityZones?: string[];
}

export class NetworkStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly nfsSecurityGroup: ec2.SecurityGroup;
  public readonly clientSecurityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props?: NetworkStackProps) {
    super(scope, id, props);

    const azs = props?.availabilityZones ?? ['us-east-1a'];

    // Single-AZ VPC with public subnet only — no NAT (cost), no private subnets needed.
    // EC2 client in public subnet uses public IP for SSM agent outbound.
    // S3 access via Gateway VPC endpoint (free).
    this.vpc = new ec2.Vpc(this, 'Vpc', {
      availabilityZones: azs,
      natGateways: 0,
      subnetConfiguration: [
        {
          name: 'public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
      ],
      gatewayEndpoints: {
        S3: { service: ec2.GatewayVpcEndpointAwsService.S3 },
      },
    });

    // SG attached to S3 Files MountTarget + EFS MountTarget.
    // Allows NFS 2049 ingress from anything inside the VPC (i.e., the EC2 client).
    this.nfsSecurityGroup = new ec2.SecurityGroup(this, 'NfsSg', {
      vpc: this.vpc,
      description: 'NFS 2049 ingress for S3 Files / EFS mount targets',
      allowAllOutbound: true,
    });
    this.nfsSecurityGroup.addIngressRule(
      ec2.Peer.ipv4(this.vpc.vpcCidrBlock),
      ec2.Port.tcp(2049),
      'NFSv4 from VPC CIDR'
    );

    // SG attached to the EC2 client itself.
    // Egress: anywhere (mount targets, S3, SSM endpoints).
    // Ingress: nothing — SSM Session Manager doesn't need inbound.
    this.clientSecurityGroup = new ec2.SecurityGroup(this, 'ClientSg', {
      vpc: this.vpc,
      description: 'EC2 fio client — SSM-managed, no inbound',
      allowAllOutbound: true,
    });

    new cdk.CfnOutput(this, 'VpcId', { value: this.vpc.vpcId });
    new cdk.CfnOutput(this, 'PublicSubnetId', {
      value: this.vpc.publicSubnets[0].subnetId,
    });
    new cdk.CfnOutput(this, 'AvailabilityZone', {
      value: this.vpc.publicSubnets[0].availabilityZone,
    });
    new cdk.CfnOutput(this, 'NfsSecurityGroupId', {
      value: this.nfsSecurityGroup.securityGroupId,
    });
  }
}
