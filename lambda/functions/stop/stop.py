import logging
import os

import boto3
import requests


logger = logging.getLogger()
logger.setLevel(logging.INFO)

ecs = boto3.client("ecs")


def handler(event, context):
    logger.info(f"Received event: {event}")
    instance_id = event.get("instance_id") or os.environ.get("SERVER_INSTANCE_ID")

    server = boto3.resource("ec2").Instance(instance_id)
    server.stop()

    resp = requests.patch(
        f"https://discord.com/api/v10/webhooks/{event['application_id']}/{event['token']}/messages/@original",
        data={
            "content": "Stopping the server",
        },
    )
    logger.info(f"Discord response ({resp.status_code}): {resp.json()}")
    return {"statusCode": 200}
