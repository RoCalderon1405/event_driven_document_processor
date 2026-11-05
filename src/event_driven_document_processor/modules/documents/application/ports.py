from typing import Protocol
from uuid import UUID

from event_driven_document_processor.modules.documents.domain.models import DocumentJob


class JobRepository(Protocol):
    def save(self, job: DocumentJob) -> None: ...

    def get(self, job_id: UUID) -> DocumentJob | None: ...
