"""Idempotent local provisioning, deliberately separate from API runtime privileges."""

import logging
import sys
from typing import TYPE_CHECKING

from botocore.exceptions import BotoCoreError, ClientError

from event_driven_document_processor.bootstrap.aws import create_dynamodb_client
from event_driven_document_processor.bootstrap.logging import configure_logging
from event_driven_document_processor.bootstrap.settings import Settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

logger = logging.getLogger(__name__)


def ensure_table(client: DynamoDBClient, table_name: str) -> None:
    """Create if absent, tolerate competing creation, and reject incompatible schemas."""
    try:
        client.describe_table(TableName=table_name)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        try:
            client.create_table(
                TableName=table_name,
                AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
                KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
                BillingMode="PAY_PER_REQUEST",
            )
        except ClientError as create_error:
            if create_error.response["Error"]["Code"] != "ResourceInUseException":
                raise
    client.get_waiter("table_exists").wait(
        TableName=table_name, WaiterConfig={"Delay": 1, "MaxAttempts": 30}
    )
    table = client.describe_table(TableName=table_name)["Table"]
    if table["KeySchema"] != [{"AttributeName": "pk", "KeyType": "HASH"}]:
        raise ValueError("Existing table must have only the pk HASH key")
    attributes = {
        entry["AttributeName"]: entry["AttributeType"] for entry in table["AttributeDefinitions"]
    }
    if attributes.get("pk") != "S":
        raise ValueError("Existing table pk must be a string")
    logger.info("DynamoDB table ready table=%s", table_name)


def main() -> int:
    """Provision only an explicitly configured local endpoint, never implicit real AWS."""
    settings = Settings()
    configure_logging(settings.log_level)
    if settings.aws_endpoint_url is None:
        logger.error("Local provisioning requires AWS_ENDPOINT_URL")
        return 1
    try:
        client = create_dynamodb_client(settings)
        try:
            ensure_table(client, settings.dynamodb_table_name)
        finally:
            client.close()
    except (BotoCoreError, ClientError, ValueError) as error:
        logger.error("DynamoDB bootstrap failed error=%s", type(error).__name__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
