#!/usr/bin/env python3

import os

from aws_cdk import App

from cdk.server_stack import GameServersStack

aws_region = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
aws_account = os.environ.get("AWS_ACCOUNT_ID", "")

app = App()
GameServersStack(
    app,
    "ValheimServerStack",  # Inaccurately named
    env={"region": aws_region, "account": aws_account},
)
app.synth()
