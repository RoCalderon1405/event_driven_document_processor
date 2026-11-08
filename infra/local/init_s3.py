"""Idempotently provision a private quarantine bucket, never delete existing objects."""

import logging
import sys
from typing import TYPE_CHECKING

from botocore.exceptions import BotoCoreError, ClientError

from event_driven_document_processor.bootstrap.aws import create_s3_client
from event_driven_document_processor.bootstrap.logging import configure_logging
from event_driven_document_processor.bootstrap.settings import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)


def ensure_bucket(
    client: S3Client, bucket: str, region: str, cors_origins: tuple[str, ...] = (),
) -> None:
    """Check before creating; enforce privacy and explicit CORS on every bootstrap."""
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        try:
            if region == "us-east-1":
                client.create_bucket(Bucket=bucket)
            else:
                client.create_bucket(
                    Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region},
                )
        except ClientError as create_error:
            if create_error.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                raise
    client.get_waiter("bucket_exists").wait(
        Bucket=bucket, WaiterConfig={"Delay": 1, "MaxAttempts": 30},
    )
    location = client.get_bucket_location(Bucket=bucket).get("LocationConstraint") or "us-east-1"
    if location != region:
        raise ValueError("Bucket region does not match configuration")
    client.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True,
        "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
    })
    client.put_bucket_ownership_controls(
        Bucket=bucket, OwnershipControls={"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
    )
    # A dedicated application bucket must have no bucket policy, including stale public policies.
    client.delete_bucket_policy(Bucket=bucket)
    client.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={
        "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}],
    })
    if cors_origins:
        client.put_bucket_cors(Bucket=bucket, CORSConfiguration={"CORSRules": [{
            "AllowedOrigins": list(cors_origins), "AllowedMethods": ["POST"],
            "AllowedHeaders": ["content-type"], "MaxAgeSeconds": 300,
        }]})
    else:
        client.delete_bucket_cors(Bucket=bucket)
    logger.info("S3 quarantine bucket ready bucket=%s", bucket)


def main() -> int:
    """Require an explicit emulator endpoint rather than provisioning implicit real AWS."""
    settings = Settings()
    configure_logging(settings.log_level)
    if settings.s3_internal_endpoint_url is None:
        logger.error("Local S3 bootstrap requires S3_INTERNAL_ENDPOINT_URL")
        return 1
    try:
        client = create_s3_client(settings)
        try:
            ensure_bucket(
                client, settings.s3_bucket_name, settings.aws_default_region,
                settings.s3_cors_allowed_origins,
            )
        finally:
            client.close()
    except (BotoCoreError, ClientError, ValueError) as error:
        code = type(error).__name__
        if isinstance(error, ClientError):
            code = error.response["Error"]["Code"]
        logger.error("S3 bootstrap failed error=%s", code)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
