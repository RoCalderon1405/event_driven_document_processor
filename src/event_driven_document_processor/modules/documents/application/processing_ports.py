"""Narrow processing boundaries without SDK, HTTP, or persistence representations."""

from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from event_driven_document_processor.modules.documents.domain.models import (
    DocumentJob,
    S3ObjectReference,
)
from event_driven_document_processor.modules.documents.domain.processing import (
    FailureCode,
    ProcessingMetadata,
)


class ProcessingStore(Protocol):
    """Atomic state changes; conditional conflicts return False, outages raise."""

    def claim(self, job: DocumentJob, claim: ProcessingMetadata, now: datetime) -> bool:
        """Select a version once, or replace its expired attempt with a new token."""
        ...

    def finish(
        self,
        job_id: UUID,
        claim: ProcessingMetadata,
        now: datetime,
        *,
        sha256: str | None = None,
        size_bytes: int | None = None,
        failure_code: FailureCode | None = None,
    ) -> bool:
        """Commit a terminal result only for the current unexpired attempt."""
        ...


class ObjectReader(Protocol):
    """Yield bounded chunks from an exact immutable version and close on every exit."""

    def read(
        self,
        reference: S3ObjectReference,
        version_id: str,
    ) -> AbstractContextManager[Iterator[bytes]]:
        """Never fall back to a latest-version read."""
        ...


class DocumentValidator(Protocol):
    """Validate a bounded, locally staged file without extracting document contents."""

    def validate(self, path: Path, content_type: str) -> None:
        """Raise InvalidDocumentError for permanently unacceptable content."""
        ...
