from uuid import uuid4

from event_driven_document_processor.modules.documents.application.service import DocumentService
from event_driven_document_processor.modules.documents.domain.enums import DocumentStatus
from event_driven_document_processor.modules.documents.infrastructure.in_memory_repository import (
    InMemoryJobRepository,
)


def test_create_job_is_pending_and_can_be_read_back():
    repository = InMemoryJobRepository()
    service = DocumentService(repository)

    job = service.create_job(
        filename="contract.pdf",
        content_type="application/pdf",
        description="Contract",
    )

    assert job.status is DocumentStatus.PENDING
    assert job.job_id.version == 4
    assert job.created_at.tzinfo is not None
    assert service.get_job(job.job_id) == job


def test_get_unknown_job_returns_none():
    service = DocumentService(InMemoryJobRepository())
    assert service.get_job(uuid4()) is None
