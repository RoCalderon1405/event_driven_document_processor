"""Transport-independent composition root for the future thin event handler."""

from functools import lru_cache

from botocore.exceptions import BotoCoreError, ClientError

from event_driven_document_processor.bootstrap.aws import create_dynamodb_client, create_s3_client
from event_driven_document_processor.bootstrap.settings import get_settings
from event_driven_document_processor.modules.documents.application.processing_errors import (
    ProcessingRetryableError,
)
from event_driven_document_processor.modules.documents.application.processing_service import (
    ProcessingService,
)
from event_driven_document_processor.modules.documents.infrastructure.document_validator import (
    IsolatedDocumentValidator,
)
from event_driven_document_processor.modules.documents.infrastructure.dynamodb_repository import (
    DynamoDBJobRepository,
)
from event_driven_document_processor.modules.documents.infrastructure.processing_store import (
    DynamoDBProcessingStore,
)
from event_driven_document_processor.modules.documents.infrastructure.s3_object_reader import (
    S3ObjectReader,
)


@lru_cache(maxsize=1)
def get_processing_service() -> ProcessingService:
    """Build lazily without adding FastAPI dependencies or installing event consumers."""
    settings = get_settings()
    try:
        dynamodb = create_dynamodb_client(settings)
        try:
            s3 = create_s3_client(settings)
        except Exception:
            dynamodb.close()
            raise
    except (BotoCoreError, ClientError, ValueError) as error:
        raise ProcessingRetryableError("Processing clients unavailable") from error
    return ProcessingService(
        DynamoDBJobRepository(dynamodb, settings.dynamodb_table_name),
        DynamoDBProcessingStore(dynamodb, settings.dynamodb_table_name),
        S3ObjectReader(s3),
        IsolatedDocumentValidator(
            timeout_seconds=settings.processing_validation_timeout_seconds,
            max_pixels=settings.processing_max_image_pixels,
            max_dimension=settings.processing_max_image_dimension,
            max_pdf_pages=settings.processing_max_pdf_pages,
            max_pdf_objects=settings.processing_max_pdf_objects,
        ),
        max_file_size_bytes=settings.processing_max_file_size_bytes,
        lease_seconds=settings.processing_lease_seconds,
        read_timeout_seconds=settings.processing_read_timeout_seconds,
    )
