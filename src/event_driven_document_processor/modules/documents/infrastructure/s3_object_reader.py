"""Private exact-version reads with bounded chunks and deterministic stream cleanup."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from botocore.exceptions import BotoCoreError, ClientError

from event_driven_document_processor.modules.documents.application.processing_errors import (
    ProcessingRetryableError,
)
from event_driven_document_processor.modules.documents.application.processing_ports import (
    ObjectReader,
)
from event_driven_document_processor.modules.documents.domain.models import S3ObjectReference

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class S3ObjectReader(ObjectReader):
    """Never substitute latest content, even when a selected version is unavailable."""

    def __init__(self, client: S3Client) -> None:
        """Use the internal-endpoint client constructed by bootstrap."""
        self._client = client

    @contextmanager
    def read(self, reference: S3ObjectReference, version_id: str) -> Iterator[Iterator[bytes]]:
        """Close on EOF, early rejection, version mismatch, and streaming SDK errors."""
        if not version_id or version_id == "null":
            raise ValueError("An exact version is required")
        body = None
        try:
            response = self._client.get_object(
                Bucket=reference.bucket,
                Key=reference.key,
                VersionId=version_id,
            )
            body = response["Body"]
            if response.get("VersionId") != version_id:
                raise ProcessingRetryableError("Object storage returned a different version")
            yield body.iter_chunks(chunk_size=64 * 1024)
        except (BotoCoreError, ClientError, OSError) as error:
            # Even 404/AccessDenied can be provisioning/event timing failures, not invalid bytes.
            raise ProcessingRetryableError("Versioned object read unavailable") from error
        finally:
            if body is not None:
                body.close()
