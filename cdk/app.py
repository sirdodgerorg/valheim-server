#!/usr/bin/env python3

import os

from aws_cdk import App

from cdk.valheim_server_stack import ValheimServerStack

aws_region = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
aws_account = os.environ.get("AWS_ACCOUNT_ID", "")

app = App()
ValheimServerStack(
    app,
    "ValheimServerStack",
    env={"region": aws_region, "account": aws_account}
)
app.synth()
