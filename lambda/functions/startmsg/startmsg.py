import json
import logging
import os

import boto3
import requests


logger = logging.getLogger()
logger.setLevel(logging.INFO)

sqs = boto3.client("sqs")


def handler(event, context):
    """SQS is used as a temporary storage space to bridge the gap between a
    Discord app sending a start command and an event-driven response. A
    queue is not the ideal solution since there is a race condition between
    multiple invocations from different servers. It would be better to use
    Redis and store the sender's token by instance id. That costs money to
    maintain though, whereas this has negligible cost. The race condition
    could be mitigated by requeuing if it were a real concern.
    """
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
                "content": f"{last_msg['application_name']} server is ready",
            },
        )

    logger.info(f"Discord response ({resp.status_code}): {resp.json()}")
    return {"statusCode": 200}
