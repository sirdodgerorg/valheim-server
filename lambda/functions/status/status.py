import logging

import boto3
import requests


logger = logging.getLogger()
logger.setLevel(logging.INFO)

ec2 = boto3.client("ec2")
ecs = boto3.client("ecs")


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

    resp = ecs.describe_services(
        cluster=event["ecs_cluster_arn"],
        services=[event["ecs_service_name"]],
    )
    desired = resp["services"][0]["desiredCount"]
    running = resp["services"][0]["runningCount"]
    pending = resp["services"][0]["pendingCount"]

    nat_instance = get_nat_instance(stack_name="ValheimServerStack")

    nat_state = nat_instance.state.get("Name") if nat_instance else "none"
    resp = requests.patch(
        f"https://discord.com/api/v10/webhooks/{event['application_id']}/{event['token']}/messages/@original",
        data={
            "content": f"Desired: {desired} | Running: {running} | Pending: {pending}; NAT: {nat_state}",
        },
    )
    logger.info(f"Discord response ({resp.status_code}): {resp.json()}")
    return {"statusCode": 200}
