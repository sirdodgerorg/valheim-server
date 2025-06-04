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
    Tags,
)


BASENAME = "Valheim"
PROJECT_TAG = "valheim"
VALHEIM_ADMINS = [
    "76561197973743697",
]


class ValheimServerStack(cdk.Stack):

    def __init__(self, scope, construct_id, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # NAT instance in non-HA mode
        nat_gateway_provider = ec2.NatInstanceProviderV2(
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T4G, ec2.InstanceSize.NANO
            ),
            machine_image=ec2.LookupMachineImage(
                name="fck-nat-al2023-*-arm64-ebs",
                owners=["568608671756"],
            ),
        )

        # VPC
        self.vpc = ec2.Vpc(
            self, f"{BASENAME}VPC", max_azs=1, nat_gateway_provider=nat_gateway_provider
        )
        Tags.of(self.vpc).add("project", PROJECT_TAG)
        nat_gateway_provider.security_group.add_ingress_rule(
            ec2.Peer.ipv4(self.vpc.vpc_cidr_block), ec2.Port.all_traffic()
        )

        # Cluster to group container instances
        self.cluster = ecs.Cluster(self, f"{BASENAME}Cluster", vpc=self.vpc)
        Tags.of(self.cluster).add("project", PROJECT_TAG)
        hosted_zone_id = os.environ.get("ROUTE53_HOSTED_ZONE_ID")
        Tags.of(self.cluster).add("ROUTE53_HOSTED_ZONE_ID", hosted_zone_id)
        Tags.of(self.cluster).add("ROUTE53_DOMAIN", os.environ.get("ROUTE53_DOMAIN"))

        # EFS filesystem for world storage
        self.efs = efs.FileSystem(
            self,
            f"{BASENAME}Filesystem",
            vpc=self.vpc,
            encrypted=False,
            lifecycle_policy=efs.LifecyclePolicy.AFTER_14_DAYS,
        )
        Tags.of(self.efs).add("project", PROJECT_TAG)

        # Volume for EFS
        self.volume = ecs.Volume(
            name=f"{BASENAME}SaveData",
            efs_volume_configuration=ecs.EfsVolumeConfiguration(
                file_system_id=self.efs.file_system_id,
            ),
        )

        # IAM execution role
        iam_task_role = iam.Role(
            self,
            f"{BASENAME}FargateTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            inline_policies={
                f"{BASENAME}S3ModsDownload": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "s3:Get*",
                                "s3:List*",
                                "s3:Describe*",
                                "s3-object-lambda:Get*",
                                "s3-object-lambda:List*",
                            ],
                            resources=[
                                "arn:aws:s3:::sirdodger-valheim-server-mods*",
                            ],
                        )
                    ]
                )
            },
        )

        # Fargate
        self.fargate_task = ecs.FargateTaskDefinition(
            self,
            f"{BASENAME}TaskDefinition",
            family=BASENAME,
            volumes=[self.volume],
            cpu=1024,  # 1 vCPU
            memory_limit_mib=4096,  # 4 GB
            task_role=iam_task_role,
        )

        self.container = self.fargate_task.add_container(
            f"{BASENAME}Container",
            image=ecs.ContainerImage.from_registry("lloesche/valheim-server"),
            logging=ecs.AwsLogDriver(
                stream_prefix=BASENAME.lower(),
                log_retention=logs.RetentionDays.ONE_WEEK,
            ),
            environment={
                "SERVER_NAME": os.environ.get("SERVER_NAME", "ServerName"),
                "WORLD_NAME": os.environ.get("WORLD_NAME", "WorldName"),
                "SERVER_PASS": os.environ.get("SERVER_PASS", ""),
                "SERVER_PUBLIC": "false",
                "ADMINLIST_IDS": " ".join(VALHEIM_ADMINS),
                "BEPINEX": "true",
                "POST_BOOTSTRAP_HOOK": "apt-get update &> /dev/null && DEBIAN_FRONTEND=noninteractive apt-get -y install awscli &> /dev/null && aws s3 sync s3://sirdodger-valheim-server-mods /config/bepinex/plugins && echo plugins downloaded",
            },
        )

        self.container.add_mount_points(
            ecs.MountPoint(
                container_path="/config/",
                read_only=False,
                source_volume=self.volume.name,
            )
        )

        self.fargate_service = ecs.FargateService(
            self,
            f"{BASENAME}FargateService",
            cluster=self.cluster,
            task_definition=self.fargate_task,
            assign_public_ip=True,
            desired_count=1,
        )
        Tags.of(self.fargate_service).add("project", PROJECT_TAG)

        # Connect to EFS over TCP port 2049
        self.fargate_service.connections.allow_from(self.efs, ec2.Port.tcp(2049))
        self.fargate_service.connections.allow_to(self.efs, ec2.Port.tcp(2049))
        # Allow connections for Valheim on UDP ports 2456-2458
        self.fargate_service.connections.allow_from(
            ec2.Peer.any_ipv4(), ec2.Port.udp_range(2456, 2458)
        )

        # Start at 1 container, but scale down every morning at 7am in case the server was left on
        autoscale = self.fargate_service.auto_scale_task_count(max_capacity=1)
        autoscale.scale_on_schedule(
            f"{BASENAME}ScaleDownSchedule",
            schedule=appscaling.Schedule.cron(hour="7", minute="0"),
            min_capacity=0,
            max_capacity=0,
            time_zone=cdk.TimeZone.AMERICA_LOS_ANGELES,
        )
        Tags.of(autoscale).add("project", PROJECT_TAG)

        # Backups

        # Back up the EFS volume every hour, retain for 3 days
        self.backup = backup.BackupPlan(self, f"{BASENAME}WorldBackupPlan")
        Tags.of(self.backup).add("project", PROJECT_TAG)
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

        # Environment for Discord -> Lambda interaction controls
        self.env_vars = {
            "APPLICATION_PUBLIC_KEY": os.environ.get("APPLICATION_PUBLIC_KEY"),
            "ECS_SERVICE_NAME": self.fargate_service.service_name,
            "ECS_CLUSTER_ARN": self.fargate_service.cluster.cluster_arn,
            "NAT_NAME": self.nat,
        }

        self.flask_lambda_layer = _lambda.LayerVersion(
            self,
            "FlaskAppLambdaLayer",
            code=_lambda.AssetCode("../lambda-requirements.zip"),
            compatible_runtimes=[
                _lambda.Runtime.PYTHON_3_12,
            ],
        )

        self.discord_interaction_handler = _lambda.Function(
            self,
            "FlaskAppLambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.AssetCode("../lambda/functions/interactions"),
            function_name="discord-interaction-handler",
            handler="discord_handler.handler",
            layers=[self.flask_lambda_layer],
            timeout=self.DURATION_60_SECONDS,
            environment={**self.env_vars},
        )
        Tags.of(self.flask_app_lambda).add("project", PROJECT_TAG)
        self.add_iam_lambda_invoke(target_lambda=self.discord_interaction_handler)

        self.server_start = self.create_server_control_lambda(
            name="start", environment=self.env_vars
        )
        Tags.of(self.server_start).add("project", PROJECT_TAG)
        self.add_iam_ecs(target_lambda=self.server_start)
        self.add_iam_ec2(target_lambda=self.server_start)

        self.server_status = self.create_server_control_lambda(
            name="status", environment=self.env_vars
        )
        Tags.of(self.server_status).add("project", PROJECT_TAG)
        self.add_iam_ec2(target_lambda=self.server_status)

        self.server_stop = self.create_server_control_lambda(
            name="stop", environment=self.env_vars
        )
        Tags.of(self.server_stop).add("project", PROJECT_TAG)
        self.add_iam_ec2(target_lambda=self.server_stop)

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
        Tags.of(self.apigateway).add("project", PROJECT_TAG)
        self.apigateway.root.add_method("ANY")
        self.discord_interaction_webhook = self.apigateway.root.add_resource("discord")
        self.discord_interaction_webhook_integration = apigw.LambdaIntegration(
            self.flask_app_lambda, request_templates=request_templates
        )
        self.discord_interaction_webhook.add_method(
            "POST", self.discord_interaction_webhook_integration
        )

        # Lambda to update Route 53 DNS
        self.dns_lambda = _lambda.Function(
            self,
            "DNSLambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.AssetCode("../lambda/functions/dns"),
            function_name="upsert-fargate-task-dns",
            handler="update_dns.handler",
            timeout=cdk.Duration.seconds(60),
        )
        self.add_iam_ecs_list_tags(
            target_lambda=self.dns_lambda,
            cluster_arn=self.fargate_service.cluster.cluster_arn,
        )
        self.add_iam_route53_update(
            target_lambda=self.dns_lambda, hosted_zone_id=hosted_zone_id
        )

        # The state change from RUNNING -> RUNNING seems to be the best since
        # the ENI is attached after the task is already running, so this is
        # the narrowest filter.
        # https://medium.com/@andreas.pasch/automatic-public-dns-for-fargate-managed-containers-in-amazon-ecs-f0ca0a0334b5
        self.subscribe_event_bridge_ecs_task_change(
            target_lambda=self.dns_lambda,
            desired_status="RUNNING",
            last_status="RUNNING",
        )

        # Lambda to stop NAT after the Fargate cluster scales down
        self.stop_nat_lambda = _lambda.Function(
            self,
            "StopNATLambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.AssetCode("../lambda/functions/nat"),
            function_name="stop-vpc-nat",
            handler="stop_nat.handler",
            timeout=cdk.Duration.seconds(60),
        )
        self.add_iam_ecs_list_tags(
            target_lambda=self.stop_nat_lambda,
            cluster_arn=self.fargate_service.cluster.cluster_arn,
        )
        self.add_iam_ec2(target_lambda=self.stop_nat_lambda)

        self.subscribe_event_bridge_ecs_task_change(
            target_lambda=self.stop_nat_lambda,
            desired_status="STOPPED",
            last_status="RUNNING",
        )

    def add_iam_ecs(self, target_lambda: _lambda.Function):
        """Permissions necessary to scale the cluster up and down.

        TODO: These permissions are overly broad.
        """
        target_lambda.add_managed_policy(
            iam.ManagedPolicy.from_managed_policy_arn(
                self,
                "ECS_FullAccessPolicy",
                managed_policy_arn="arn:aws:iam::aws:policy/AmazonECS_FullAccess",
            )
        )

    def add_iam_ec2(self, target_lambda: _lambda.Function):
        """Permission to start an ec2 instance.

        TODO: The resource ARN is unknown since the instance is created on demand,
        but see if tighter permissions can be achieved by setting conditions on
        the cluster/task creating the instance.

        Also needs access to the NAT instance.
        """
        target_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["ec2:Describe*", "ec2:StartInstances", "ec2:StopInstances"],
                resources=["*"],
                conditions={
                    "StringEquals": {
                        "aws:ResourceTag/project": PROJECT_TAG,
                    },
                },
            )
        )

    def add_iam_ecs_list_tags(self, target_lambda: _lambda.Function, cluster_arn: str):
        """Permission to list tags for the cluster."""
        target_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "ecs:ListTagsForResource",
                ],
                resources=[cluster_arn],
            )
        )

    def add_iam_lambda_invoke(self, target_lambda: _lambda.Function):
        """Permission to invoke Valheim server control lambdas."""

        target_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["lambda:InvokeFunction"],
                resources=["arn:aws:lambda:::function:valheim*"],
                conditions={
                    "StringEquals": {
                        "aws:ResourceTag/project": PROJECT_TAG,
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

    def create_server_control_lambda(self, name: str, environment: dict):
        return _lambda.Function(
            self,
            f"{BASENAME}{name.capitalize()}Lambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.AssetCode(f"../lambda/functions/{name}"),
            function_name=f"{BASENAME.lower()}-{name}",
            handler=f"{name}.handler",
            layers=[],
            timeout=cdk.Duration.seconds(60),
            environment=environment,
        )

    def subscribe_event_bridge_ecs_task_change(
        self, target_lambda: _lambda.Function, desired_status: str, last_status: str
    ):
        event_pattern = events.EventPattern(
            source=["aws.ecs"],
            detail_type=["ECS Task State Change"],
            detail={"desiredStatus": [desired_status], "lastStatus": [last_status]},
            # EventBridge is not matching this ARN and delivering the event to the lambda
            # resources=[f"arn:aws:ecs:::task/{self.cluster.cluster_name}/*"],
        )
        event_rule = events.Rule(
            self,
            f"{target_lambda.id}EventRule",
            event_pattern=event_pattern,
        )
        event_rule.add_target(
            aws_events_targets.LambdaFunction(
                target_lambda,
                retry_attempts=0,
            )
        )
