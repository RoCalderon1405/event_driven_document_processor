"""DynamoDB adapter. JOB# keys are active; HASH# is reserved, not implemented."""

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError

from event_driven_document_processor.modules.documents.application.errors import (
    PersistenceDataError,
    PersistenceUnavailableError,
)
from event_driven_document_processor.modules.documents.application.ports import JobRepository
from event_driven_document_processor.modules.documents.domain.enums import DocumentStatus
from event_driven_document_processor.modules.documents.domain.models import (
    DocumentJob,
    S3ObjectReference,
)
from event_driven_document_processor.modules.documents.infrastructure.processing_mapping import (
    deserialize_processing,
    serialize_processing,
)

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient
    from mypy_boto3_dynamodb.type_defs import AttributeValueTypeDef

logger = logging.getLogger(__name__)


def _log_failure(operation: str, job_id: UUID, error: BotoCoreError | ClientError) -> None:
    """Log only safe context, never the SDK exception's message or item contents."""
    code = type(error).__name__
    request_id = "unknown"
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code", code)
        request_id = error.response.get("ResponseMetadata", {}).get("RequestId", request_id)
    logger.error(
        "DynamoDB operation=%s job_id=%s error=%s request_id=%s",
        operation,
        job_id,
        code,
        request_id,
    )


class DynamoDBJobRepository(JobRepository):
    """Store immutable jobs behind the unchanged save/get repository contract."""

    def __init__(self, client: DynamoDBClient, table_name: str) -> None:
        self._client = client
        self._table_name = table_name

    def save(self, job: DocumentJob) -> None:
        """Replace a job by key, matching the in-memory adapter's save semantics."""
        item: dict[str, AttributeValueTypeDef] = {
            "pk": {"S": f"JOB#{job.job_id}"},
            "job_id": {"S": str(job.job_id)},
            "filename": {"S": job.filename},
            "content_type": {"S": job.content_type},
            "description": {"NULL": True} if job.description is None else {"S": job.description},
            "status": {"S": job.status.value},
            "created_at": {"S": job.created_at.isoformat()},
        }
        if job.object_reference is not None:
            item["object_reference"] = {
                "M": {
                    "bucket": {"S": job.object_reference.bucket},
                    "key": {"S": job.object_reference.key},
                }
            }
        if job.declared_size_bytes is not None:
            item["declared_size_bytes"] = {"N": str(job.declared_size_bytes)}
        if job.processing is not None:
            item["processing"] = {"M": serialize_processing(job.processing)}
        try:
            self._client.put_item(TableName=self._table_name, Item=item)
        except (BotoCoreError, ClientError) as error:
            _log_failure("PutItem", job.job_id, error)
            raise PersistenceUnavailableError("Job storage unavailable") from error

    def get(self, job_id: UUID) -> DocumentJob | None:
        """Read consistently; only a successful response without Item means missing."""
        try:
            response = self._client.get_item(
                TableName=self._table_name,
                Key={"pk": {"S": f"JOB#{job_id}"}},
                ConsistentRead=True,
            )
        except (BotoCoreError, ClientError) as error:
            _log_failure("GetItem", job_id, error)
            raise PersistenceUnavailableError("Job storage unavailable") from error
        if "Item" not in response:
            return None
        try:
            return self._from_item(response["Item"], job_id)
        except (KeyError, ValueError, TypeError, AttributeError) as error:
            logger.error("Invalid stored job operation=GetItem job_id=%s", job_id)
            raise PersistenceDataError("Invalid stored job") from error

    @staticmethod
    def _from_item(item: dict[str, AttributeValueTypeDef], job_id: UUID) -> DocumentJob:
        stored_id = UUID(item["job_id"]["S"])
        if stored_id != job_id or item["pk"]["S"] != f"JOB#{job_id}":
            raise ValueError("Job key mismatch")
        created_at = datetime.fromisoformat(item["created_at"]["S"])
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Timestamp must include timezone")
        description = item["description"]
        reference = None
        if "object_reference" in item:
            stored_reference = item["object_reference"]["M"]
            reference = S3ObjectReference(
                bucket=stored_reference["bucket"]["S"],
                key=stored_reference["key"]["S"],
            )
        return DocumentJob(
            job_id=stored_id,
            filename=item["filename"]["S"],
            content_type=item["content_type"]["S"],
            description=None if description.get("NULL") is True else description["S"],
            status=DocumentStatus(item["status"]["S"]),
            created_at=created_at,
            object_reference=reference,
            declared_size_bytes=(
                int(item["declared_size_bytes"]["N"]) if "declared_size_bytes" in item else None
            ),
            processing=(
                deserialize_processing(item["processing"]["M"]) if "processing" in item else None
            ),
        )
