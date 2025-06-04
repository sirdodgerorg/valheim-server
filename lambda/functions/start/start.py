import logging

import boto3
import requests


logger = logging.getLogger()
logger.setLevel(logging.INFO)

ec2 = boto3.client("ec2")
ecs = boto3.client("ecs")


def get_nat_instance(name: str):
    """Retrieve the NAT instance"""

    response = ec2.describe_instances(
        Filters=[
            {
                "Name": "tag:Name",
                "Values": [name],
            },
        ],
    )
    instance_id = response["Reservations"][0]["Instances"][0]["InstanceId"]
    return boto3.resource("ec2").Instance(instance_id)


def handler(event, context):
    logger.info(f"Received event: {event}")

    content = "Starting the server"
    nat_instance = get_nat_instance()

    # Start NAT
    nat_instance.start()

    # Scale up Fargate server
    resp = ecs.update_service(
        cluster=event["ecs_cluster_arn"],
        service=event["ecs_service_name"],
        desiredCount=1,
    )

    url = f"https://discord.com/api/v10/webhooks/{event['application_id']}/{event['token']}/messages/@original"
    data = {
        "type": 4,
        "data": {
            "content": content,
            "embeds": [],
            "allowed_mentions": {"parse": []},
        },
    }
    logger.info(f"Editing message: {url} with {data}")
    resp = requests.patch(url, data=data)
    logger.info(f"Discord response: {resp.json}")
    return {"statusCode": 200}
