import logging

import boto3
import requests


logger = logging.getLogger()
logger.setLevel(logging.INFO)

ecs = boto3.client("ecs")


def handler(event, context):
    logger.info(f"Received event: {event}")

    # Scale down Fargate server
    resp = ecs.update_service(
        cluster=event["ecs_cluster_arn"],
        service=event["ecs_service_name"],
        desiredCount=0,
    )

    resp = requests.patch(
        f"https://discord.com/api/v10/webhooks/{event['application_id']}/{event['token']}/messages/@original",
        data={
            "content": "Stopping the server",
        },
    )
    logger.info(f"Discord response ({resp.status_code}): {resp.json()}")
    return {"statusCode": 200}
