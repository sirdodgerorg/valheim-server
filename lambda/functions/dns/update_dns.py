import logging

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def fetch_cluster_tags(cluster_arn: str) -> dict[str, str]:
    """
    Fetches the tags for a given cluster.

    Args:
        cluster_arn (str): The ARN of the cluster.

    Returns:
        dict[str, str]: A dictionary of tags.
    """
    client = boto3.client("ecs")
    response = client.list_tags_for_resource(resourceArn=cluster_arn)
    return {t["key"]: t["value"] for t in response["tags"]}


def get_eni_id(task) -> str:
    """
    Gets the ENI ID for a given task.

    Args:
        task (dict): The task dictionary.

    Returns:
        str: The ENI ID.
    """
    for attachment in task["attachments"]:
        for detail in attachment["details"]:
            if detail["name"] == "networkInterfaceId":
                return detail["value"]


def get_eni_public_ip(eni_id: str) -> str:
    """
    Gets the public IP for a given ENI ID.

    Args:
        eni_id (str): The ENI ID.

    Returns:
        str: The public IP.
    """
    client = boto3.client("ec2")
    response = client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
    logger.info(f"ENI response: {response}")
    return response["NetworkInterfaces"][0].get("Association", {}).get("PublicIp")


def upsert_route53_recordset(
    cluster_name: str, hosted_zone_id: str, domain: str, public_ip: str
) -> bool:
    """
    Upserts a route53 recordset.

    Args:
        domain (str): The domain name.
        public_ip (str): The public IP.

    Returns:
        dict: The response from the route53 API.
    """

    change = {
        "Action": "UPSERT",
        "ResourceRecordSet": {
            "Name": domain,
            "Type": "A",
            "TTL": 60,
            "ResourceRecords": [{"Value": public_ip}],
        },
    }

    client = boto3.client("route53")
    response = client.change_resource_record_sets(
        HostedZoneId=hosted_zone_id,
        ChangeBatch={
            "Comment": f"Updated by XXXXXX-fargate-task-dns lambda for cluster {cluster_name}",
            "Changes": [change],
        },
    )
    logger.info(f"Route53 response: {response}")

    if response["ResponseMetadata"]["HTTPStatusCode"] == 200:
        return True


def handler(event, context):

    logger.info(f"Received event: {event}")

    task = event["detail"]
    cluster_arn = task["clusterArn"]
    cluster_name = cluster_arn.split(":cluster/")[1]

    tags = fetch_cluster_tags(cluster_arn=cluster_arn)
    logger.info(f"Fetched tags: {tags}")
    domain = tags.get("ROUTE53_DOMAIN")
    hosted_zone_id = tags.get("ROUTE53_HOSTED_ZONE_ID")

    if not domain:
        logger.info(f"Cluster {cluster_name} missing domain tag, skipping DNS update")
        return

    if not hosted_zone_id:
        logger.info(
            f"Cluster {cluster_name} missing hosted_zone_id tag, skipping DNS update"
        )
        return

    eni_id = get_eni_id(task=task)
    if not eni_id:
        logger.info(
            f"Task {task["taskArn"]} missing network interface, skipping DNS update"
        )
        return

    task_public_ip = get_eni_public_ip(eni_id=eni_id)
    if not task_public_ip:
        logger.info(f"Task {task["taskArn"]} missing public IP, skipping DNS update")
        return

    success = upsert_route53_recordset(
        cluster_name=cluster_name,
        hosted_zone_id=hosted_zone_id,
        domain=domain,
        public_ip=task_public_ip,
    )

    if success:
        logger.info(f"Successfully updated DNS for {cluster_name} to {task_public_ip}")
        return {"statusCode": 200}

    raise Exception(f"Failed to update DNS")
