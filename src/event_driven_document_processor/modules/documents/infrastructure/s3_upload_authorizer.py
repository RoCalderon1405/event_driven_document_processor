"""Boto3 presigned POST adapter; no object bytes pass through the API."""

import logging
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError

from event_driven_document_processor.modules.documents.application.errors import (
    UploadAuthorizationUnavailableError,
)
from event_driven_document_processor.modules.documents.application.ports import UploadAuthorizer
from event_driven_document_processor.modules.documents.application.upload_models import (
    UploadAuthorization,
)
from event_driven_document_processor.modules.documents.domain.models import S3ObjectReference

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)


class S3UploadAuthorizer(UploadAuthorizer):
    """Sign an exact key, MIME field, and file length with a short-lived POST policy."""

    def __init__(self, client: S3Client, bucket: str, expires_in_seconds: int) -> None:
        self._client = client
        self._bucket = bucket
        self._expires_in_seconds = expires_in_seconds

    def authorize(
        self,
        job_id: UUID,
        *,
        content_type: str,
        file_size_bytes: int,
    ) -> UploadAuthorization:
        key = f"quarantine/{job_id}/{uuid4().hex}"
        try:
            post = self._client.generate_presigned_post(
                Bucket=self._bucket,
                Key=key,
                Fields={"Content-Type": content_type},
                Conditions=[
                    {"Content-Type": content_type},
                    ["content-length-range", file_size_bytes, file_size_bytes],
                ],
                ExpiresIn=self._expires_in_seconds,
            )
        except (BotoCoreError, ClientError, ValueError) as error:
            logger.error(
                "S3 operation=PresignPost job_id=%s error=%s",
                job_id,
                type(error).__name__,
            )
            raise UploadAuthorizationUnavailableError("Upload signing unavailable") from error
        return UploadAuthorization(
            object_reference=S3ObjectReference(bucket=self._bucket, key=key),
            url=post["url"],
            fields=post["fields"],
            expires_in_seconds=self._expires_in_seconds,
        )
