"""Construct AWS clients at the composition boundary."""

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from event_driven_document_processor.bootstrap.settings import Settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient


def create_dynamodb_client(settings: Settings) -> DynamoDBClient:
    """Create a thread-safe low-level client with bounded retries and I/O timeouts."""
    return boto3.client(
        "dynamodb",
        endpoint_url=str(settings.aws_endpoint_url) if settings.aws_endpoint_url else None,
        region_name=settings.aws_default_region,
        config=Config(
            connect_timeout=settings.aws_connect_timeout,
            read_timeout=settings.aws_read_timeout,
            retries={"mode": "standard", "total_max_attempts": settings.aws_max_attempts},
        ),
    )
