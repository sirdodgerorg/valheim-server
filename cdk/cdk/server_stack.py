import os

import aws_cdk as cdk
from aws_cdk import (
    aws_apigateway as apigw,
    aws_applicationautoscaling as appscaling,
    aws_backup as backup,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_efs as efs,
    aws_events as events,
    aws_events_targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_logs_destinations as logs_destinations,
    aws_sqs as sqs,
    Tags,
)


# Note that many of the original resources will be named for the original
# Valheim server even though they are shared. If we ever do a full destroy,
# opportunistically change this to "Servers"
BASENAME = "Valheim"
PROJECT_TAG_KEY = "project"

LAMBDA_DISCORD_BASE_NAME = "servers"

TAG_MORIA = "moria"
TAG_SERVERS = "servers"
TAG_VALHEIM = "valheim"


class GameServersStack(cdk.Stack):

    def __init__(self, scope, construct_id, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        route53_domain_base = os.environ.get("ROUTE53_DOMAIN_BASE")
        route53_zone_id = os.environ.get("ROUTE53_HOSTED_ZONE_ID")

        # VPC
        self.vpc = ec2.Vpc(
            self,
            f"{BASENAME}VPC",
            max_azs=1,
            ip_addresses=ec2.IpAddresses.cidr("172.31.0.0/16"),
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                    map_public_ip_on_launch=True,
                ),
            ],
        )
        Tags.of(self.vpc).add(PROJECT_TAG_KEY, TAG_SERVERS)

        # EC2 Key Pair
        self.keypair = ec2.KeyPair(
            self,
            f"{BASENAME}ServerKeyPair",  # Named Valheim but serves both
            format=ec2.KeyPairFormat.PPK,
            key_pair_name=f"{BASENAME}Server",  # Named Valheim but serves both
        )
        Tags.of(self.keypair).add(PROJECT_TAG_KEY, TAG_VALHEIM)  # Old tag name

        ##################################################
        # Shared storage for all servers
        ##################################################

        # EFS filesystem for world storage
        self.efs = efs.FileSystem(
            self,
            f"{BASENAME}Filesystem",  # Named Valheim but serves both
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            encrypted=False,
            lifecycle_policy=efs.LifecyclePolicy.AFTER_14_DAYS,
        )
        Tags.of(self.efs).add(PROJECT_TAG_KEY, TAG_VALHEIM)  # Old tag name

        # Volume for EFS
        self.volume = ecs.Volume(
            name=f"{BASENAME}SaveData",
            efs_volume_configuration=ecs.EfsVolumeConfiguration(
                file_system_id=self.efs.file_system_id,
            ),
        )

        # Backups
        # Back up the EFS volume every hour, retain for 3 days
        self.backup = backup.BackupPlan(self, f"{BASENAME}BackupPlan")
        Tags.of(self.backup).add(PROJECT_TAG_KEY, TAG_VALHEIM)
        self.backup.add_selection(
            f"{BASENAME}BackupSelection",
            resources=[backup.BackupResource.from_efs_file_system(self.efs)],
        )
        self.backup.add_rule(
            backup.BackupPlanRule(
                schedule_expression=events.Schedule.cron(minute="0"),
                delete_after=cdk.Duration.days(3),
            )
        )

        ##################################################
        # Valheim server
        ##################################################

        # EC2 Server Instance - Valheim
        self.ec2_valheim = ec2.Instance(
            self,
            f"ValheimServer",
            instance_type=ec2.InstanceType.of(
                instance_class=ec2.InstanceClass.T3A,
                instance_size=ec2.InstanceSize.MEDIUM,
            ),
            machine_image=ec2.MachineImage.generic_linux(
                ami_map={"us-west-2": "ami-03aa99ddf5498ceb9"}
            ),
            key_pair=self.keypair,
            allow_all_outbound=True,
            associate_public_ip_address=True,
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )
        Tags.of(self.ec2_valheim).add(PROJECT_TAG_KEY, TAG_VALHEIM)
        Tags.of(self.ec2_valheim).add("ROUTE53_HOSTED_ZONE_ID", route53_zone_id)
        Tags.of(self.ec2_valheim).add("ROUTE53_DOMAIN", f"valheim{route53_domain_base}")

        # Add Cloudwatch logging roles
        self.ec2_valheim.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "CloudWatchAgentServerPolicy"
            )
        )
        self.ec2_valheim.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonSSMManagedInstanceCore"
            )
        )

        # Construct the ARN for use in IAM policies, etc.
        ec2_valheim_arn = cdk.Stack.format_arn(
            self,
            partition="aws",
            service="ec2",
            region=self.region,
            account=self.account,
            resource="instance",
            resource_name=self.ec2_valheim.instance_id,
            arn_format=cdk.ArnFormat.SLASH_RESOURCE_NAME,
        )

        # CloudWatch Log Group for application logs
        self.log_group_valheim = logs.LogGroup(
            self,
            f"ValheimLogGroup",
            log_group_name=f"/aws/ec2/valheim",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # CloudWatch Log Group for syslog
        self.log_group_valheim_syslog = logs.LogGroup(
            self,
            f"ValheimSyslogLogGroup",
            log_group_name=f"/aws/ec2/valheim-syslog",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # Allow connections for Valheim on UDP ports 2456-2458
        self.ec2_valheim.connections.allow_from(
            ec2.Peer.any_ipv4(), ec2.Port.udp_range(2456, 2458)
        )

        self.efs.connections.allow_default_port_from(self.ec2_valheim)

        ##################################################
        # Moria server
        ##################################################

        # EC2 Server Instance - Moria
        self.ec2_moria = ec2.Instance(
            self,
            f"MoriaServer",
            instance_type=ec2.InstanceType.of(
                instance_class=ec2.InstanceClass.T3A,
                instance_size=ec2.InstanceSize.MEDIUM,
            ),
            machine_image=ec2.MachineImage.generic_linux(
                ami_map={"us-west-2": "ami-03aa99ddf5498ceb9"}
            ),
            key_pair=self.keypair,
            allow_all_outbound=True,
            associate_public_ip_address=True,
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )
        Tags.of(self.ec2_moria).add(PROJECT_TAG_KEY, TAG_MORIA)
        Tags.of(self.ec2_moria).add("ROUTE53_HOSTED_ZONE_ID", route53_zone_id)
        Tags.of(self.ec2_moria).add("ROUTE53_DOMAIN", f"moria{route53_domain_base}")

        # Add Cloudwatch logging roles
        self.ec2_moria.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "CloudWatchAgentServerPolicy"
            )
        )
        self.ec2_moria.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonSSMManagedInstanceCore"
            )
        )

        # Construct the ARN for use in IAM policies, etc.
        ec2_moria_arn = cdk.Stack.format_arn(
            self,
            partition="aws",
            service="ec2",
            region=self.region,
            account=self.account,
            resource="instance",
            resource_name=self.ec2_moria.instance_id,
            arn_format=cdk.ArnFormat.SLASH_RESOURCE_NAME,
        )

        # CloudWatch Log Group for application logs
        self.log_group_moria = logs.LogGroup(
            self,
            f"MoriaLogGroup",
            log_group_name=f"/aws/ec2/moria",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # CloudWatch Log Group for syslog
        self.log_group_moria_syslog = logs.LogGroup(
            self,
            f"MoriaSyslogLogGroup",
            log_group_name=f"/aws/ec2/moria-syslog",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # Allow connections for Valheim on UDP ports 7777
        self.ec2_moria.connections.allow_from(ec2.Peer.any_ipv4(), ec2.Port.udp(7777))

        self.efs.connections.allow_default_port_from(self.ec2_moria)

        # Allow connections for SSH
        self.ec2_moria.connections.allow_from(ec2.Peer.any_ipv4(), ec2.Port.tcp(22))

        ##################################################
        # Discord control
        ##################################################

        # Queues for events between lambdas
        self.server_start_queue = sqs.Queue(
            self,
            f"{BASENAME}ServerStartQueue",
            retention_period=cdk.Duration.minutes(15),
        )
        Tags.of(self.server_start_queue).add(PROJECT_TAG_KEY, TAG_SERVERS)

        # Environment for Discord -> Lambda interaction controls
        self.env_vars = {
            "APPLICATION_PUBLIC_KEY": os.environ.get("APPLICATION_PUBLIC_KEY"),
            "SERVER_INSTANCE_ID": self.ec2_valheim.instance_id,
            "SQS_SERVER_START_URL": self.server_start_queue.queue_url,
            "ROUTE53_DOMAIN_BASE": route53_domain_base,
            "ROUTE53_HOSTED_ZONE_ID": route53_zone_id,
        }

        lambda_layer = _lambda.LayerVersion(
            self,
            "FlaskAppLambdaLayer",
            code=_lambda.AssetCode("../lambda-requirements.zip"),
            compatible_runtimes=[
                _lambda.Runtime.PYTHON_3_12,
            ],
        )

        self.lambda_discord = self.create_lambda(
            name="discord", environment=self.env_vars, layers=[lambda_layer]
        )

        Tags.of(self.lambda_discord).add(PROJECT_TAG_KEY, TAG_SERVERS)
        self.add_iam_lambda_invoke(target_lambda=self.lambda_discord)

        self.server_start = self.create_lambda(
            name="start", environment=self.env_vars, layers=[lambda_layer]
        )
        Tags.of(self.server_start).add(PROJECT_TAG_KEY, TAG_SERVERS)

        self.add_iam_ec2(target_lambda=self.server_start, instance_arn=ec2_valheim_arn)
        self.add_iam_ec2(target_lambda=self.server_start, instance_arn=ec2_moria_arn)

        self.add_iam_ec2_describe(target_lambda=self.server_start)
        self.add_iam_sqs(
            target_lambda=self.server_start, target_queue=self.server_start_queue
        )

        self.lambda_startmsg = self.create_lambda(
            name="startmsg", environment=self.env_vars, layers=[lambda_layer]
        )
        self.add_iam_sqs(
            target_lambda=self.lambda_startmsg,
            target_queue=self.server_start_queue,
        )

        self.server_start_subscription_filter_valheim = logs.SubscriptionFilter(
            self,
            f"{BASENAME}LogSubscriptionFilter",
            log_group=self.log_group_valheim,
            destination=logs_destinations.LambdaDestination(self.lambda_startmsg),
            filter_pattern=logs.FilterPattern.literal(r"%.*Opened Steam server%"),
        )

        self.lambda_status = self.create_lambda(
            name="status", environment=self.env_vars, layers=[lambda_layer]
        )
        Tags.of(self.lambda_status).add(PROJECT_TAG_KEY, TAG_SERVERS)
        self.add_iam_ec2_describe(target_lambda=self.lambda_status)

        self.lambda_stop = self.create_lambda(
            name="stop", environment=self.env_vars, layers=[lambda_layer]
        )
        Tags.of(self.lambda_stop).add(PROJECT_TAG_KEY, TAG_SERVERS)
        self.add_iam_ec2(target_lambda=self.lambda_stop, instance_arn=ec2_valheim_arn)
        self.add_iam_ec2(target_lambda=self.lambda_stop, instance_arn=ec2_moria_arn)
        self.add_iam_ec2_describe(target_lambda=self.lambda_stop)

        # https://slmkitani.medium.com/passing-custom-headers-through-amazon-api-gateway-to-an-aws-lambda-function-f3a1cfdc0e29
        request_templates = {
            "application/json": """{
                "method": "$context.httpMethod",
                "body" : $input.json("$"),
                "headers": {
                    #foreach($param in $input.params().header.keySet())
                    "$param": "$util.escapeJavaScript($input.params().header.get($param))"
                    #if($foreach.hasNext),#end
                    #end
                }
            }
            """
        }

        self.apigateway = apigw.RestApi(self, "FlaskAppEndpoint")
        Tags.of(self.apigateway).add(PROJECT_TAG_KEY, TAG_SERVERS)
        self.apigateway.root.add_method("ANY")

        self.discord_interaction_webhook_valheim = self.apigateway.root.add_resource(
            "valheim"
        )
        self.discord_interaction_webhook_integration_valheim = apigw.LambdaIntegration(
            self.lambda_discord, request_templates=request_templates
        )
        self.discord_interaction_webhook_valheim.add_method(
            "POST", self.discord_interaction_webhook_integration_valheim
        )

        self.discord_interaction_webhook_moria = self.apigateway.root.add_resource(
            "moria"
        )
        self.discord_interaction_webhook_integration_moria = apigw.LambdaIntegration(
            self.lambda_discord, request_templates=request_templates
        )
        self.discord_interaction_webhook_moria.add_method(
            "POST", self.discord_interaction_webhook_integration_moria
        )

        # Lambda to update Route 53 DNS
        self.lambda_updatedns = self.create_lambda(
            name="updatedns", environment=self.env_vars, layers=[]
        )
        self.add_iam_ec2_describe(target_lambda=self.lambda_updatedns)
        self.add_iam_route53_update(
            target_lambda=self.lambda_updatedns, hosted_zone_id=route53_zone_id
        )

        # Subscribe to running state change to update dns
        self.subscribe_event_bridge_ec2_state_change(
            name="Valheim",
            target_lambda=self.lambda_updatedns,
            instance_arn=ec2_valheim_arn,
            state="running",
        )
        self.subscribe_event_bridge_ec2_state_change(
            name="Moria",
            target_lambda=self.lambda_updatedns,
            instance_arn=ec2_moria_arn,
            state="running",
        )

    def add_iam_ec2(self, target_lambda: _lambda.Function, instance_arn: str):
        """Permission to start/stop an ec2 instance."""
        target_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["ec2:StartInstances", "ec2:StopInstances"],
                resources=[instance_arn],
            )
        )

    def add_iam_ec2_describe(self, target_lambda: _lambda.Function):
        """Permission to describe an ec2 instance. Describe* actions do not allow
        resource/condition constraints."""
        target_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW, actions=["ec2:Describe*"], resources=["*"]
            )
        )

    def add_iam_lambda_invoke(self, target_lambda: _lambda.Function):
        """Permission to invoke Valheim server control lambdas."""

        target_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["lambda:InvokeFunction"],
                resources=[
                    f"arn:aws:lambda:us-west-2:399585304222:function:{LAMBDA_DISCORD_BASE_NAME}-start",
                    f"arn:aws:lambda:us-west-2:399585304222:function:{LAMBDA_DISCORD_BASE_NAME}-status",
                    f"arn:aws:lambda:us-west-2:399585304222:function:{LAMBDA_DISCORD_BASE_NAME}-stop",
                ],
                conditions={
                    "StringEquals": {
                        "aws:ResourceTag/project": TAG_SERVERS,
                    },
                },
            )
        )

    def add_iam_route53_update(
        self, target_lambda: _lambda.Function, hosted_zone_id: str
    ):
        target_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "ec2:DescribeNetworkInterfaces",
                ],
                resources=[
                    # No task exists yet, so no ENI exists yet either.  Grant the
                    # Lambda wide access to fetching ENI details
                    "*",
                ],
            )
        )
        target_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "route53:ChangeResourceRecordSets",
                ],
                resources=[
                    f"arn:aws:route53:::hostedzone/{hosted_zone_id}",
                ],
            )
        )

    def add_iam_sqs(self, target_lambda: _lambda.Function, target_queue: sqs.Queue):
        """Permission to enqueue and read SQS messages."""

        target_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "sqs:SendMessage",
                    "sqs:ReceiveMessage",
                ],
                resources=[target_queue.queue_arn],
            )
        )

    def create_lambda(
        self, name: str, environment: dict, layers: list[_lambda.LayerVersion]
    ):
        log_group = logs.LogGroup(
            self,
            f"LambdaServers{name.capitalize()}LogGroup",
            log_group_name=f"/aws/lambda/{LAMBDA_DISCORD_BASE_NAME}-{name}",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        return _lambda.Function(
            self,
            f"Servers{name.capitalize()}Lambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.AssetCode(f"../lambda/functions/{name}"),
            function_name=f"{LAMBDA_DISCORD_BASE_NAME}-{name}",
            handler=f"{name}.handler",
            layers=layers,
            timeout=cdk.Duration.seconds(30),
            log_group=log_group,
            environment=environment,
        )

    def subscribe_event_bridge_ec2_state_change(
        self, name: str, target_lambda: _lambda.Function, instance_arn: str, state: str
    ):
        event_pattern = events.EventPattern(
            source=["aws.ec2"],
            detail_type=["EC2 Instance State-change Notification"],
            detail={"state": [state]},
            resources=[instance_arn],
        )
        event_rule = events.Rule(
            self,
            f"{name}{target_lambda.node.id}EventRule",
            event_pattern=event_pattern,
        )
        event_rule.add_target(
            aws_events_targets.LambdaFunction(
                target_lambda,
                retry_attempts=0,
            )
        )
