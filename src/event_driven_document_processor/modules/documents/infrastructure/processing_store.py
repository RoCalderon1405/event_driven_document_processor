"""DynamoDB version selection and token/lease-fenced transitions using UpdateItem only."""

from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError

from event_driven_document_processor.modules.documents.application.errors import (
    PersistenceUnavailableError,
)
from event_driven_document_processor.modules.documents.application.processing_ports import (
    ProcessingStore,
)
from event_driven_document_processor.modules.documents.domain.models import DocumentJob
from event_driven_document_processor.modules.documents.domain.processing import (
    FailureCode,
    ProcessingMetadata,
)
from event_driven_document_processor.modules.documents.infrastructure.dynamodb_repository import (
    _log_failure,
)
from event_driven_document_processor.modules.documents.infrastructure.processing_mapping import (
    serialize_processing,
    timestamp,
)

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient
    from mypy_boto3_dynamodb.type_defs import AttributeValueTypeDef


class DynamoDBProcessingStore(ProcessingStore):
    """Keep creation's save/get contract separate from concurrent processing writes."""

    def __init__(self, client: DynamoDBClient, table_name: str) -> None:
        """Share the bootstrap-owned low-level client without owning its lifecycle."""
        self._client = client
        self._table = table_name

    def claim(self, job: DocumentJob, claim: ProcessingMetadata, now: datetime) -> bool:
        """First successful claim wins; only that same version can recover after expiry."""
        if job.object_reference is None:
            return False
        if not claim.version_id or claim.version_id == "null" or claim.lease_expires_at <= now:
            raise ValueError("A claim requires an exact version and a future lease")
        return self._update(
            job.job_id,
            "SET #status = :processing_status, #processing = :claim",
            "attribute_exists(pk) AND object_reference.#bucket = :bucket "
            "AND object_reference.#key = :key AND "
            "((#status = :pending AND attribute_not_exists(#processing)) OR "
            "(#status = :processing_status AND #processing.version_id = :version "
            "AND #processing.lease_expires_at <= :now))",
            {"#status": "status", "#processing": "processing", "#key": "key", "#bucket": "bucket"},
            {
                ":processing_status": {"S": "PROCESSING"},
                ":pending": {"S": "PENDING"},
                ":claim": {"M": serialize_processing(claim)},
                ":version": {"S": claim.version_id},
                ":now": {"S": timestamp(now)},
                ":bucket": {"S": job.object_reference.bucket},
                ":key": {"S": job.object_reference.key},
            },
        )

    def finish(
        self,
        job_id: UUID,
        claim: ProcessingMetadata,
        now: datetime,
        *,
        sha256: str | None = None,
        size_bytes: int | None = None,
        failure_code: FailureCode | None = None,
    ) -> bool:
        """An old, expired, or already-terminated worker cannot publish any result."""
        if failure_code is None and (sha256 is None or size_bytes is None):
            raise ValueError("Completion requires a digest and actual byte length")
        if failure_code is not None and (sha256 is not None or size_bytes is not None):
            raise ValueError("Failure must not include completion facts")
        result = replace(
            claim,
            finished_at=now,
            sha256=sha256,
            size_bytes=size_bytes,
            failure_code=failure_code,
        )
        return self._update(
            job_id,
            "SET #status = :terminal, #processing = :result",
            "#status = :processing_status AND #processing.#token = :token "
            "AND #processing.version_id = :version AND #processing.lease_expires_at > :now",
            {"#status": "status", "#processing": "processing", "#token": "token"},
            {
                ":terminal": {"S": "FAILED" if failure_code else "COMPLETED"},
                ":processing_status": {"S": "PROCESSING"},
                ":result": {"M": serialize_processing(result)},
                ":token": {"S": claim.token},
                ":version": {"S": claim.version_id},
                ":now": {"S": timestamp(now)},
            },
        )

    def _update(
        self,
        job_id: UUID,
        update: str,
        condition: str,
        names: dict[str, str],
        values: dict[str, AttributeValueTypeDef],
    ) -> bool:
        """Conditional conflicts are expected; all other SDK failures remain retryable."""
        try:
            self._client.update_item(
                TableName=self._table,
                Key={"pk": {"S": f"JOB#{job_id}"}},
                UpdateExpression=update,
                ConditionExpression=condition,
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            _log_failure("UpdateItem", job_id, error)
            raise PersistenceUnavailableError("Processing storage unavailable") from error
        except BotoCoreError as error:
            _log_failure("UpdateItem", job_id, error)
            raise PersistenceUnavailableError("Processing storage unavailable") from error
        return True
