"""Create upload-enabled jobs without changing metadata-only job behavior."""

from datetime import UTC, datetime
from uuid import uuid4

from event_driven_document_processor.modules.documents.application.errors import (
    UploadValidationError,
)
from event_driven_document_processor.modules.documents.application.ports import (
    JobRepository,
    UploadAuthorizer,
)
from event_driven_document_processor.modules.documents.application.upload_models import (
    UploadJobResult,
)
from event_driven_document_processor.modules.documents.domain.enums import DocumentStatus
from event_driven_document_processor.modules.documents.domain.models import DocumentJob


class UploadService:
    """Validate, authorize locally, persist, then return; never persist signing fields."""

    def __init__(
        self,
        repository: JobRepository,
        authorizer: UploadAuthorizer,
        *,
        allowed_content_types: tuple[str, ...],
        max_file_size_bytes: int,
    ) -> None:
        self._repository = repository
        self._authorizer = authorizer
        self._allowed_content_types = allowed_content_types
        self._max_file_size_bytes = max_file_size_bytes

    def create_upload_job(
        self,
        *,
        filename: str,
        content_type: str,
        file_size_bytes: int,
        description: str | None = None,
    ) -> UploadJobResult:
        """Issue authorization only for validated metadata and successfully saved jobs."""
        if (
            not isinstance(filename, str)
            or not filename.strip()
            or len(filename) > 255
            or filename in {".", ".."}
            or any(c in filename for c in "/\\")
            or any(ord(c) < 32 or ord(c) == 127 for c in filename)
        ):
            raise UploadValidationError("filename must be a nonempty display name without paths")
        if content_type not in self._allowed_content_types:
            raise UploadValidationError("content_type is not enabled for uploads")
        if type(file_size_bytes) is not int or not 0 < file_size_bytes <= self._max_file_size_bytes:
            raise UploadValidationError("file_size_bytes is outside the permitted upload size")
        if description is not None and (not isinstance(description, str) or len(description) > 500):
            raise UploadValidationError("description must contain at most 500 characters")
        job_id = uuid4()
        authorization = self._authorizer.authorize(
            job_id,
            content_type=content_type,
            file_size_bytes=file_size_bytes,
        )
        job = DocumentJob(
            job_id=job_id,
            filename=filename,
            content_type=content_type,
            description=description,
            status=DocumentStatus.PENDING,
            created_at=datetime.now(UTC),
            object_reference=authorization.object_reference,
            declared_size_bytes=file_size_bytes,
        )
        self._repository.save(job)
        return UploadJobResult(job=job, upload=authorization)
