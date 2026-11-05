from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from event_driven_document_processor.modules.documents.domain.enums import DocumentStatus


@dataclass(frozen=True, slots=True)
class DocumentJob:
    job_id: UUID
    filename: str
    content_type: str
    description: str | None
    status: DocumentStatus
    created_at: datetime
