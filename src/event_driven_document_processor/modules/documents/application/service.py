from datetime import UTC, datetime
from uuid import UUID, uuid4

from event_driven_document_processor.modules.documents.application.ports import JobRepository
from event_driven_document_processor.modules.documents.domain.enums import DocumentStatus
from event_driven_document_processor.modules.documents.domain.models import DocumentJob


class DocumentService:
    def __init__(self, repository: JobRepository) -> None:
        self._repository = repository

    def create_job(
        self,
        *,
        filename: str,
        content_type: str,
        description: str | None = None,
    ) -> DocumentJob:
        job = DocumentJob(
            job_id=uuid4(),
            filename=filename,
            content_type=content_type,
            description=description,
            status=DocumentStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        self._repository.save(job)
        return job

    def get_job(self, job_id: UUID) -> DocumentJob | None:
        return self._repository.get(job_id)
