import logging
from functools import lru_cache
from typing import Annotated

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends

from event_driven_document_processor.bootstrap.aws import create_dynamodb_client, create_s3_client
from event_driven_document_processor.bootstrap.settings import get_settings
from event_driven_document_processor.modules.documents.application.errors import (
    PersistenceUnavailableError,
    UploadAuthorizationUnavailableError,
)
from event_driven_document_processor.modules.documents.application.ports import (
    JobRepository,
    UploadAuthorizer,
)
from event_driven_document_processor.modules.documents.application.service import DocumentService
from event_driven_document_processor.modules.documents.application.upload_service import (
    UploadService,
)
from event_driven_document_processor.modules.documents.infrastructure.dynamodb_repository import (
    DynamoDBJobRepository,
)
from event_driven_document_processor.modules.documents.infrastructure.s3_upload_authorizer import (
    S3UploadAuthorizer,
)


@lru_cache(maxsize=1)
def get_document_repository() -> JobRepository:
    """Construct the process-wide runtime adapter; isolated tests override this provider."""
    settings = get_settings()
    try:
        client = create_dynamodb_client(settings)
    except (BotoCoreError, ClientError) as error:
        logging.getLogger(__name__).error(
            "AWS client initialization failed error=%s", type(error).__name__
        )
        raise PersistenceUnavailableError("Job storage unavailable") from error
    return DynamoDBJobRepository(client, settings.dynamodb_table_name)


def get_document_service(
    repository: Annotated[JobRepository, Depends(get_document_repository)],
) -> DocumentService:
    return DocumentService(repository)


@lru_cache(maxsize=1)
def get_upload_authorizer() -> UploadAuthorizer:
    """Construct the public-endpoint signer without weakening local signature checks."""
    settings = get_settings()
    try:
        client = create_s3_client(settings, public=True)
    except (BotoCoreError, ClientError, ValueError) as error:
        logging.getLogger(__name__).error(
            "S3 client initialization failed error=%s",
            type(error).__name__,
        )
        raise UploadAuthorizationUnavailableError("Upload signing unavailable") from error
    return S3UploadAuthorizer(client, settings.s3_bucket_name, settings.upload_expires_in_seconds)


def get_upload_service(
    repository: Annotated[JobRepository, Depends(get_document_repository)],
    authorizer: Annotated[UploadAuthorizer, Depends(get_upload_authorizer)],
) -> UploadService:
    """Inject a narrow signer and plain policy values, not Settings into application code."""
    settings = get_settings()
    return UploadService(
        repository,
        authorizer,
        allowed_content_types=settings.upload_allowed_content_types,
        max_file_size_bytes=settings.upload_max_file_size_bytes,
    )
