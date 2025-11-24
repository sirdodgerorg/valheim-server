import json
import logging
import os

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)

ec2 = boto3.client("ec2")
ecs = boto3.client("ecs")
sqs = boto3.client("sqs")


def handler(event, context):
    logger.info(f"Received event: {event}")
    instance_id = event.get("instance_id") or os.environ.get("SERVER_INSTANCE_ID")
    ec2.start_instances(InstanceIds=[instance_id])

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
    return {"statusCode": 200}
