import json
import logging
import os

import awsgi
import boto3
from discord_interactions import verify_key_decorator
from flask import Flask, jsonify, request


INTERACTIONS = {"start", "stop", "status"}
# Map of Discord applications to ec2 instance ids
SERVER_INSTANCES = {
    "1442796677156175966": "i-09d189bb90d2212ac",  # Moria
    "1370896965881299065": "i-000a7e7cda25c4842",  # Valheim
}
SERVER_NAMES = {
    "1442796677156175966": "Moria",  # Moria
    "1370896965881299065": "Valheim",  # Valheim
}


logger = logging.getLogger()
logger.setLevel(logging.INFO)

app = Flask(__name__)
aws_lambda = boto3.client("lambda")


@app.route("/moria", methods=["POST"])
@verify_key_decorator(
    "4763ec4eebb1d89859f3a41ec601ff238f8b5a6047d9961b9590c1d533410658"
)
def moria():
    """https://discord.com/developers/applications/1442796677156175966/information"""
    return discord()


@app.route("/valheim", methods=["POST"])
@verify_key_decorator(
    "e9f996f69a848f285e4444a41f50f3b485321e7906744e6a97ef4bde0a20ddf3"
)
def valheim():
    """https://discord.com/developers/applications/1370896965881299065/information"""
    return discord()


def discord():
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

        app_id = request_json["application_id"]
        payload = {
            # Pass Discord application_id and token to edit the response from other lambdas
            "application_id": app_id,
            "application_name": SERVER_NAMES.get(app_id),
            "instance_id": SERVER_INSTANCES.get(app_id),
            "token": request_json["token"],
        }

        aws_lambda.invoke(
            FunctionName=f"servers-{interaction_option}",
            InvocationType="Event",
            Payload=json.dumps(payload),
        )

        # Type 4 with data content will return a message. Type 5 shows a thinking
        # spinner and does not mark the message as edited when a response is async
        # patched.
        # response = {
        #     "type": 4,  # Respond with message
        #     "data": {
        #         "tts": False,
        #         "content": "",
        #         "embeds": [],
        #         "allowed_mentions": {"parse": []},
        #     },
        # }
        return jsonify({"type": 5})


def handler(event, context):
    return awsgi.response(app, event, context, base64_content_types={"image/png"})
