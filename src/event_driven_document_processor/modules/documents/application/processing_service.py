"""Shared processing orchestration, independent of event transport and AWS SDKs."""

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from uuid import UUID, uuid4

from event_driven_document_processor.modules.documents.application.ports import JobRepository
from event_driven_document_processor.modules.documents.application.processing_errors import (
    InvalidDocumentError,
    InvalidProcessingEventError,
    ProcessingRetryableError,
)
from event_driven_document_processor.modules.documents.application.processing_ports import (
    DocumentValidator,
    ObjectReader,
    ProcessingStore,
)
from event_driven_document_processor.modules.documents.domain.enums import DocumentStatus
from event_driven_document_processor.modules.documents.domain.models import S3ObjectReference
from event_driven_document_processor.modules.documents.domain.processing import (
    FailureCode,
    ProcessingMetadata,
)

logger = logging.getLogger(__name__)


class ProcessingOutcome(StrEnum):
    """Acknowledgable outcomes; active/lost claims instead raise retryable errors."""

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ALREADY_TERMINAL = "ALREADY_TERMINAL"
    OTHER_VERSION = "OTHER_VERSION"


class ProcessingService:
    """Claim, stage/hash, validate, and fence the result without full-item saves."""

    def __init__(
        self,
        repository: JobRepository,
        store: ProcessingStore,
        reader: ObjectReader,
        validator: DocumentValidator,
        *,
        max_file_size_bytes: int,
        lease_seconds: int = 180,
        read_timeout_seconds: float = 60,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Inject plain policies and a clock; adapters own all external representations."""
        if max_file_size_bytes <= 0 or lease_seconds <= 0 or read_timeout_seconds <= 0:
            raise ValueError("Processing limits must be positive")
        self._repository = repository
        self._store = store
        self._reader = reader
        self._validator = validator
        self._max_size = max_file_size_bytes
        self._lease_seconds = lease_seconds
        self._read_timeout = read_timeout_seconds
        self._clock = clock

    def process(
        self,
        job_id: UUID,
        reference: S3ObjectReference,
        version_id: str,
    ) -> ProcessingOutcome:
        """Process an already-decoded reference; transport parsing belongs to Phase 3."""
        if not isinstance(version_id, str) or not version_id.strip() or version_id == "null":
            raise InvalidProcessingEventError("An immutable object version is required")
        job = self._repository.get(job_id)
        if job is None or job.object_reference != reference:
            raise InvalidProcessingEventError("Event does not match an upload-enabled job")
        if job.processing is not None and job.processing.version_id != version_id:
            return ProcessingOutcome.OTHER_VERSION
        if job.status in {
            DocumentStatus.COMPLETED,
            DocumentStatus.FAILED,
            DocumentStatus.DUPLICATE,
        }:
            return ProcessingOutcome.ALREADY_TERMINAL
        now = self._clock()
        claim = ProcessingMetadata(
            version_id,
            str(uuid4()),
            now,
            now + timedelta(seconds=self._lease_seconds),
        )
        if not self._store.claim(job, claim, now):
            # A competing write is not absence or successful work. Redelivery re-reads state.
            raise ProcessingRetryableError("Claim conflicted; retry from a fresh snapshot")
        self._log(job_id, "claimed")
        digest = hashlib.sha256()
        size = 0
        failure = None
        try:
            with TemporaryDirectory(prefix="document-processing-") as directory:
                path = Path(directory) / "document"
                deadline = monotonic() + self._read_timeout
                with path.open("wb") as target, self._reader.read(reference, version_id) as chunks:
                    for chunk in chunks:
                        if monotonic() > deadline:
                            raise ProcessingRetryableError("Object read deadline exceeded")
                        size += len(chunk)
                        if size > self._max_size:
                            raise InvalidDocumentError(FailureCode.TOO_LARGE)
                        digest.update(chunk)
                        target.write(chunk)
                if size == 0:
                    raise InvalidDocumentError(FailureCode.EMPTY)
                if job.declared_size_bytes is not None and size != job.declared_size_bytes:
                    raise InvalidDocumentError(FailureCode.SIZE_MISMATCH)
                self._validator.validate(path, job.content_type)
        except InvalidDocumentError as error:
            failure = error.code
        except OSError as error:
            raise ProcessingRetryableError("Local staging unavailable") from error
        # An expired worker may have done valid work but has no authority to publish it.
        if not self._store.finish(
            job_id,
            claim,
            self._clock(),
            sha256=digest.hexdigest() if failure is None else None,
            size_bytes=size if failure is None else None,
            failure_code=failure,
        ):
            raise ProcessingRetryableError("Processing claim no longer owns the result")
        outcome = ProcessingOutcome.FAILED if failure else ProcessingOutcome.COMPLETED
        self._log(job_id, outcome.value, failure)
        return outcome

    @staticmethod
    def _log(job_id: UUID, event: str, failure: FailureCode | None = None) -> None:
        """Log structured identifiers and fixed codes, never references or parser output."""
        logger.info(
            "document_processing job_id=%s event=%s failure_code=%s",
            job_id,
            event,
            failure.value if failure else "none",
            extra={
                "job_id": str(job_id),
                "processing_event": event,
                "failure_code": failure.value if failure else None,
            },
        )
