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

    resp = ecs.describe_services(
        cluster=event["ecs_cluster_arn"],
        services=[event["ecs_service_name"]],
    )
    desired = resp["services"][0]["desiredCount"]
    running = resp["services"][0]["runningCount"]
    pending = resp["services"][0]["pendingCount"]

    nat_instance = get_nat_instance()
    nat_state = nat_instance.state.get("Name") if nat_instance else "none"

    content = f"Desired: {desired} | Running: {running} | Pending: {pending}; NAT: {nat_state}"
    url = f"https://discord.com/api/v10/webhooks/{event['application_id']}/{event['token']}/messages/@original"
    data = {
        "type": 4,
        "data": {
            "content": content,
            "embeds": [],
            "allowed_mentions": {"parse": []},
        },
    }
    logger.info(f"Updating: {url} with {data}")
    requests.patch(url, data=data)
    return {"statusCode": 200}
