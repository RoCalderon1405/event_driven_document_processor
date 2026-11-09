"""Resource-bounded format validation; this is neither malware scanning nor extraction."""

import subprocess
import sys
from pathlib import Path

from event_driven_document_processor.modules.documents.application.processing_errors import (
    InvalidDocumentError,
    ProcessingRetryableError,
)
from event_driven_document_processor.modules.documents.application.processing_ports import (
    DocumentValidator,
)
from event_driven_document_processor.modules.documents.domain.processing import FailureCode

WORKER_MODULE = "event_driven_document_processor.modules.documents.infrastructure.validation_worker"
RESULT_CODES = {
    20: FailureCode.INVALID_FORMAT,
    21: FailureCode.FORMAT_MISMATCH,
    22: FailureCode.RESOURCE_LIMIT,
}


class IsolatedDocumentValidator(DocumentValidator):
    """Run native decoders in a disposable process with a wall-clock deadline."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 15,
        max_pixels: int = 20_000_000,
        max_dimension: int = 16_384,
        max_pdf_pages: int = 500,
        max_pdf_objects: int = 50_000,
    ) -> None:
        """Accept explicit parser budgets, independently of compressed upload length."""
        self._timeout = timeout_seconds
        self._limits = (max_pixels, max_dimension, max_pdf_pages, max_pdf_objects)
        if not 0 < timeout_seconds <= 60 or any(value <= 0 for value in self._limits):
            raise ValueError("Validation budgets must be positive and deadline at most 60 seconds")

    def validate(self, path: Path, content_type: str) -> None:
        """Discard all parser diagnostics: file-controlled messages never reach logs."""
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    WORKER_MODULE,
                    str(path),
                    content_type,
                    *(str(value) for value in self._limits),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise InvalidDocumentError(FailureCode.RESOURCE_LIMIT) from error
        except OSError as error:
            raise ProcessingRetryableError("Validator could not start") from error
        if result.returncode in RESULT_CODES:
            raise InvalidDocumentError(RESULT_CODES[result.returncode])
        if result.returncode != 0:
            # A missing library or native crash is not evidence of invalid document content.
            raise ProcessingRetryableError("Validator process unavailable")
