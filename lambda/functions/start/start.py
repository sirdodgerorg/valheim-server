import json
import logging
import os

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)

ec2 = boto3.client("ec2")
ecs = boto3.client("ecs")
sqs = boto3.client("sqs")


def get_nat_instance(stack_name: str):
    """Retrieve the NAT instance"""
    ec2 = boto3.client("ec2")
    response = ec2.describe_instances(
        Filters=[
            {
                "Name": "tag:Name",
                "Values": [
                    f"{stack_name}/ValheimVPC/PublicSubnet1/NatInstance",
                ],
            },
        ],
    )
    instance_id = response["Reservations"][0]["Instances"][0]["InstanceId"]
    return boto3.resource("ec2").Instance(instance_id)


def handler(event, context):
    logger.info(f"Received event: {event}")

    nat_instance = get_nat_instance(stack_name="ValheimServerStack")

    # Start NAT
    nat_instance.start()

    # Scale up Fargate server
    resp = ecs.update_service(
        cluster=event["ecs_cluster_arn"],
        service=event["ecs_service_name"],
        desiredCount=1,
    )

    # Enqueue message to SQS to allow follow-up message
    sqs.send_message(
        QueueUrl=os.environ.get("SQS_SERVER_START_URL"),
        MessageBody=json.dumps(
            {
                "application_id": event["application_id"],
                "token": event["token"],
            }
        ),
    )

    # Defer response until after server is ready
    # resp = requests.patch(
    #     f"https://discord.com/api/v10/webhooks/{event['application_id']}/{event['token']}/messages/@original",
    #     data={
    #         "content": "Starting the server",
    #     },
    # )
    # logger.info(f"Discord response ({resp.status_code}): {resp.json()}")
    return {"statusCode": 200}
