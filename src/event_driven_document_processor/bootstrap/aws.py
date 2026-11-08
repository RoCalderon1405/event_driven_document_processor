"""Construct AWS clients at the composition boundary."""

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from event_driven_document_processor.bootstrap.settings import Settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient
    from mypy_boto3_s3 import S3Client


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


def create_s3_client(settings: Settings, *, public: bool = False) -> S3Client:
    """Use the actual caller's endpoint for signing; never rewrite generated URLs."""
    endpoint = settings.s3_public_endpoint_url if public else settings.s3_internal_endpoint_url
    if public and endpoint is None and (
        settings.s3_internal_endpoint_url is not None or settings.aws_endpoint_url is not None
    ):
        raise ValueError("A public S3 endpoint is required with local AWS endpoints")
    return boto3.client(
        "s3",
        endpoint_url=str(endpoint) if endpoint else None,
        region_name=settings.aws_default_region,
        config=Config(
            signature_version="s3v4", s3={"addressing_style": "path"},
            connect_timeout=settings.aws_connect_timeout,
            read_timeout=settings.aws_read_timeout,
            retries={"mode": "standard", "total_max_attempts": settings.aws_max_attempts},
        ),
    )
