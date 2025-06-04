import json
import logging
import os

import awsgi
import boto3
from discord_interactions import verify_key_decorator
from flask import Flask, jsonify, request


INTERACTIONS = {"start", "stop", "status"}

# Your public key can be found on your application in the Developer Portal
PUBLIC_KEY = os.environ.get("APPLICATION_PUBLIC_KEY")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

app = Flask(__name__)
aws_lambda = boto3.client("lambda")


@app.route("/discord", methods=["POST"])
@verify_key_decorator(PUBLIC_KEY)
def index():
    """Discord interaction Lambda must return within three seconds or else Discord marks
    the interaction as a failure.  Perform significant work in secondary lambdas.
    """
    request_json = request.json

    # Respond to ping
    if request_json["type"] == 1:
        return jsonify({"type": 1})
    # Process command
    else:
        logger.info(f"Request: {request_json}")
        try:
            interaction_option = request_json["data"]["options"][0]["value"]
        except KeyError:
            interaction_option = None
            logger.error("Unparseable interaction option")

        if interaction_option not in INTERACTIONS:
            logger.error("Invalid interaction option: %s", interaction_option)
            raise ValueError

        logger.info(f"Interaction: {interaction_option}")

        payload = {
            # Pass Discord application_id and token to edit the response from other lambdas
            "application_id": request_json["application_id"],
            "token": request_json["token"],
            # Pass environmental info identifying resources to query/modify
            "ecs_cluster_arn": os.environ.get("ECS_CLUSTER_ARN", ""),
            "ecs_service_name": os.environ.get("ECS_SERVICE_NAME", ""),
            "nat_name": "ValheimServerStack/ValheimVPC/PublicSubnet1/NatInstance",
        }

        aws_lambda.invoke(
            FunctionName=f"valheim-{interaction_option}",
            InvocationType="Event",
            Payload=json.dumps(payload),
        )

        response = {
            "type": 4,  # Respond with message
            "data": {
                "tts": False,
                "content": "Pending...",
                "embeds": [],
                "allowed_mentions": {"parse": []},
            },
        }
        return jsonify(response)


def handler(event, context):
    return awsgi.response(app, event, context, base64_content_types={"image/png"})
