import logging
import os

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)


ec2 = boto3.client("ec2")
route53 = boto3.client("route53")

SERVER_DOMAIN = {
    "1442796677156175966": "moria",
    "1370896965881299065": "valheim",
}


def upsert_route53_recordset(hosted_zone_id: str, domain: str, public_ip: str) -> bool:
    """
    Upserts a route53 recordset.

    Args:
        hosted_zone_id (str): The route53 zone id.
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
    response = route53.change_resource_record_sets(
        HostedZoneId=hosted_zone_id,
        ChangeBatch={
            "Comment": f"Updated by lambda",
            "Changes": [change],
        },
    )
    logger.info(f"Route53 response: {response}")

    if response["ResponseMetadata"]["HTTPStatusCode"] == 200:
        return True


def handler(event, context):
    logger.info("Received event: %s", event)
    instance_id = event["detail"]["instance-id"]
    desc = ec2.describe_instances(InstanceIds=[instance_id])
    try:
        public_ip = desc["Reservations"][0]["Instances"][0]["PublicIpAddress"]
    except (KeyError, IndexError) as ex:
        logger.error("Could not get IP address: %s", ex)
        raise

    domain = f"{SERVER_DOMAIN.get(instance_id)}{os.environ.get("ROUTE53_DOMAIN_BASE")}"
    hosted_zone_id = os.environ.get("ROUTE53_HOSTED_ZONE_ID")
    success = upsert_route53_recordset(
        hosted_zone_id=hosted_zone_id,
        domain=domain,
        public_ip=public_ip,
    )

    if success:
        logger.info(f"Successfully updated DNS for {instance_id} to {public_ip}")
        return {"statusCode": 200}

    raise Exception(f"Failed to update DNS")
