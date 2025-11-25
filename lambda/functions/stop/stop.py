import logging
import os

import boto3
import requests


logger = logging.getLogger()
logger.setLevel(logging.INFO)

ecs = boto3.client("ecs")


def handler(event, context):
    logger.info(f"Received event: {event}")
    server = boto3.resource("ec2").Instance(event.get("instance_id"))
    server.stop()
    resp = requests.patch(
        f"https://discord.com/api/v10/webhooks/{event['application_id']}/{event['token']}/messages/@original",
        data={
            "content": f"{event['application_name']} server is stopped",
        },
    )
    logger.info(f"Discord response ({resp.status_code}): {resp.json()}")
    return {"statusCode": 200}
