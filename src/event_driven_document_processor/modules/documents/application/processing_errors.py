"""Sanitized processing errors; retryable failures must not become FAILED jobs."""

from event_driven_document_processor.modules.documents.domain.processing import FailureCode


class ProcessingRetryableError(Exception):
    """Infrastructure, active leases, or lost fencing require a later delivery."""


class InvalidProcessingEventError(Exception):
    """An event cannot identify a saved job's exact versioned object."""


class InvalidDocumentError(Exception):
    """A permanent content/policy violation with no sensitive parser message."""

    def __init__(self, code: FailureCode) -> None:
        self.code = code
        super().__init__(code.value)
