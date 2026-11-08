from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from event_driven_document_processor.modules.documents.domain.enums import DocumentStatus


@dataclass(frozen=True, slots=True)
class S3ObjectReference:
    """Durable object location, without credentials or temporary authorization."""

    bucket: str
    key: str

    def __post_init__(self) -> None:
        if not isinstance(self.bucket, str) or not self.bucket.strip():
            raise ValueError("Object bucket must be nonempty")
        if not isinstance(self.key, str) or not self.key.strip():
            raise ValueError("Object key must be nonempty")


@dataclass(frozen=True, slots=True)
class DocumentJob:
    job_id: UUID
    filename: str
    content_type: str
    description: str | None
    status: DocumentStatus
    created_at: datetime
    object_reference: S3ObjectReference | None = None
