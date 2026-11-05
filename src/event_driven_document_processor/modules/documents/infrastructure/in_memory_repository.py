from threading import Lock
from uuid import UUID

from event_driven_document_processor.modules.documents.domain.models import DocumentJob


class InMemoryJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[UUID, DocumentJob] = {}
        self._lock = Lock()

    def save(self, job: DocumentJob) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def get(self, job_id: UUID) -> DocumentJob | None:
        with self._lock:
            return self._jobs.get(job_id)
