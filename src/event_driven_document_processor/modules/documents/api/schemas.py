from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from event_driven_document_processor.modules.documents.domain.enums import DocumentStatus


class CreateDocumentRequest(BaseModel):
    filename: str = Field(
        min_length=1,
        max_length=255,
        validation_alias=AliasChoices("filename", "file_name"),
    )
    content_type: Literal["application/pdf", "image/png", "image/jpeg"]
    description: str | None = Field(default=None, max_length=500)


class DocumentJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: UUID
    filename: str
    content_type: str
    description: str | None
    status: DocumentStatus
    created_at: datetime
