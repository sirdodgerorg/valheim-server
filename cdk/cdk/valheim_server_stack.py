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

        # VPC
        self.vpc = ec2.Vpc(self, f"{BASENAME}VPC", max_azs=1)
        Tags.of(self.vpc).add("project", PROJECT_TAG)

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

        # Environment for Discord -> Lambda server
        self.env_vars = {
            "APPLICATION_PUBLIC_KEY": os.environ.get("APPLICATION_PUBLIC_KEY"),
            "ECS_SERVICE_NAME": self.fargate_service.service_name,
            "ECS_CLUSTER_ARN": self.fargate_service.cluster.cluster_arn,
        }

        self.flask_lambda_layer = _lambda.LayerVersion(
            self,
            "FlaskAppLambdaLayer",
            code=_lambda.AssetCode("../lambda-requirements.zip"),
            compatible_runtimes=[
                _lambda.Runtime.PYTHON_3_12,
            ],
        )

        self.flask_app_lambda = _lambda.Function(
            self,
            "FlaskAppLambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.AssetCode("../lambda/functions/interactions"),
            function_name="discord-interaction-handler",
            handler="discord_handler.handler",
            layers=[self.flask_lambda_layer],
            timeout=cdk.Duration.seconds(60),
            environment={**self.env_vars},
        )
        Tags.of(self.flask_app_lambda).add("project", PROJECT_TAG)

        self.flask_app_lambda.role.add_managed_policy(
            iam.ManagedPolicy.from_managed_policy_arn(
                self,
                "ECS_FullAccessPolicy",
                managed_policy_arn="arn:aws:iam::aws:policy/AmazonECS_FullAccess",
            )
        )

        # https://slmkitani.medium.com/passing-custom-headers-through-amazon-api-gateway-to-an-aws-lambda-function-f3a1cfdc0e29
        self.request_templates = {
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
            self.flask_app_lambda, request_templates=self.request_templates
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
        self.dns_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "ecs:ListTagsForResource",
                ],
                resources=[self.fargate_service.cluster.cluster_arn],
            )
        )
        self.dns_lambda.add_to_role_policy(
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
        self.dns_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "route53:ChangeResourceRecordSets",
                ],
                resources=[
                    # Hardcoded hosted zone for the NS subdomain
                    f"arn:aws:route53:::hostedzone/{hosted_zone_id}",
                ],
            )
        )

        # The state change from RUNNING -> RUNNING seems to be the best since
        # the ENI is attached after the task is already running, so this is
        # the narrowest filter.
        # https://medium.com/@andreas.pasch/automatic-public-dns-for-fargate-managed-containers-in-amazon-ecs-f0ca0a0334b5
        dns_lambda_event_pattern = events.EventPattern(
            source=["aws.ecs"],
            detail_type=["ECS Task State Change"],
            detail={"desiredStatus": ["RUNNING"], "lastStatus": ["RUNNING"]},
            # EventBridge is not matching this ARN and delivering the event to the lambda
            # resources=[f"arn:aws:ecs:::task/{self.cluster.cluster_name}/*"],
        )
        dns_lambda_event_rule = events.Rule(
            self,
            "DNSLambdaEventRule",
            event_pattern=dns_lambda_event_pattern,
        )
        dns_lambda_event_rule.add_target(
            aws_events_targets.LambdaFunction(
                self.dns_lambda,
                retry_attempts=0,
            )
        )
