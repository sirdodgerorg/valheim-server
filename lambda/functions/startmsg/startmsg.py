import json
import logging
import os

import boto3
import requests


logger = logging.getLogger()
logger.setLevel(logging.INFO)

sqs = boto3.client("sqs")


def handler(event, context):
    logger.info(f"Received event: {event}")

    # Pull from queue to update message here
    sqs_resp = sqs.receive_message(
        QueueUrl=os.environ.get("SQS_SERVER_START_URL"),
        MaxNumberOfMessages=10,
    )

    last_msg = None
    if sqs_resp:
        logger.info("Fetched %s message(s)", len(sqs_resp["Messages"]))
        for sqs_message in sqs_resp["Messages"]:
            last_msg = json.loads(sqs_message["Body"])

    if last_msg:
        logger.info("Updating Discord message")
        resp = requests.patch(
            f"https://discord.com/api/v10/webhooks/{last_msg['application_id']}/{last_msg['token']}/messages/@original",
            data={
                "content": "Server is ready",
            },
        )

    logger.info(f"Discord response ({resp.status_code}): {resp.json()}")
    return {"statusCode": 200}
