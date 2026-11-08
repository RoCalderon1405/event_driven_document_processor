"""Plain application results: no HTTP framework or AWS SDK types."""

from dataclasses import dataclass, field

from event_driven_document_processor.modules.documents.domain.models import (
    DocumentJob,
    S3ObjectReference,
)


@dataclass(frozen=True, slots=True)
class UploadAuthorization:
    """Ephemeral bearer authorization; signing material is excluded from repr."""

    object_reference: S3ObjectReference
    url: str = field(repr=False)
    fields: dict[str, str] = field(repr=False)
    expires_in_seconds: int


@dataclass(frozen=True, slots=True)
class UploadJobResult:
    """A persisted pending job and its short-lived direct-upload authorization."""

    job: DocumentJob
    upload: UploadAuthorization
