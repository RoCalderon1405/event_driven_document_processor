from typing import Protocol
from uuid import UUID

from event_driven_document_processor.modules.documents.application.upload_models import (
    UploadAuthorization,
)
from event_driven_document_processor.modules.documents.domain.models import DocumentJob


class JobRepository(Protocol):
    def save(self, job: DocumentJob) -> None: ...

    def get(self, job_id: UUID) -> DocumentJob | None: ...


class UploadAuthorizer(Protocol):
    """Authorize a single exact object upload without transferring file bytes."""

    def authorize(
        self, job_id: UUID, *, content_type: str, file_size_bytes: int,
    ) -> UploadAuthorization: ...
