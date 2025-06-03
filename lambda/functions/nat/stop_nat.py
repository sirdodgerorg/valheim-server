import boto3


def fetch_cluster_tags(cluster_arn: str) -> dict[str, str]:
    """
    Fetches the tags for a given cluster.

    Args:
        cluster_arn (str): The ARN of the cluster.

    Returns:
        dict[str, str]: A dictionary of tags.
    """
    ecs = boto3.client("ecs")
    response = ecs.list_tags_for_resource(resourceArn=cluster_arn)
    return {t["key"]: t["value"] for t in response["tags"]}


def get_nat_instance(stack_name: str):
    """Retrieve the NAT instance"""
    ec2 = boto3.client("ec2")
    response = ec2.describe_instances(
        Filters=[
            {
                "Name": "tag:Name",
                "Values": [
                    f"{stack_name}/ValheimVPC/PublicSubnet1/NatInstance",
                ],
            },
        ],
    )
    instance_id = response["Reservations"][0]["Instances"][0]["InstanceId"]
    return boto3.resource("ec2").Instance(instance_id)


def handler(event, context):

    print(f"Received event: {event}")

    task = event["detail"]
    cluster_arn = task["clusterArn"]

    tags = fetch_cluster_tags(cluster_arn=cluster_arn)
    print(f"Fetched tags: {tags}")

    stack_name = tags.get("aws:cloudformation:stack-name")
    if stack_name == "ValheimServerStack":
        nat_instance = get_nat_instance(stack_name=stack_name)
        print(f"Stopping NAT instance: {nat_instance.instance_id}")
        nat_instance.stop()

    return {"statusCode": 200}
