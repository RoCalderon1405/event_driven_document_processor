import logging
from functools import lru_cache
from typing import Annotated

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends

from event_driven_document_processor.bootstrap.aws import create_dynamodb_client
from event_driven_document_processor.bootstrap.settings import get_settings
from event_driven_document_processor.modules.documents.application.errors import (
    PersistenceUnavailableError,
)
from event_driven_document_processor.modules.documents.application.ports import JobRepository
from event_driven_document_processor.modules.documents.application.service import DocumentService
from event_driven_document_processor.modules.documents.infrastructure.dynamodb_repository import (
    DynamoDBJobRepository,
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
