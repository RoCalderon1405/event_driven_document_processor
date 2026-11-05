from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from event_driven_document_processor.modules.documents.application.ports import JobRepository
from event_driven_document_processor.modules.documents.application.service import DocumentService
from event_driven_document_processor.modules.documents.infrastructure.in_memory_repository import (
    InMemoryJobRepository,
)


@lru_cache(maxsize=1)
def get_document_repository() -> InMemoryJobRepository:
    return InMemoryJobRepository()


def get_document_service(
    repository: Annotated[JobRepository, Depends(get_document_repository)],
) -> DocumentService:
    return DocumentService(repository)
