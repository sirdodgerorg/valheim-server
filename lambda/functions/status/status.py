import logging
import os

import boto3
import requests


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    logger.info(f"Received event: {event}")
    instance_id = event.get("instance_id") or os.environ.get("SERVER_INSTANCE_ID")
    server = boto3.resource("ec2").Instance(instance_id)

    if server:
        try:
            describe_response = boto3.client("ec2").describe_instance_status(
                InstanceIds=[instance_id]
            )
            health_check = f" ({describe_response["InstanceStatuses"][0]["InstanceStatus"]["Status"]})"
        except (IndexError, KeyError):
            health_check = ""
        status = f"{server.state.get("Name")}{health_check}"
    else:
        status = "No instance found"

    resp = requests.patch(
        f"https://discord.com/api/v10/webhooks/{event['application_id']}/{event['token']}/messages/@original",
        data={"content": f"Status: {status}"},
    )
    logger.info(f"Discord response ({resp.status_code}): {resp.json()}")
    return {"statusCode": 200}
