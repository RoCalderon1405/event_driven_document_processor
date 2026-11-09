"""Lazy transport-independent composition and environment budget validation."""

from unittest.mock import Mock

import pytest
from botocore.exceptions import NoCredentialsError
from pydantic import ValidationError

from event_driven_document_processor.bootstrap import processing
from event_driven_document_processor.bootstrap.settings import Settings
from event_driven_document_processor.modules.documents.application.processing_errors import (
    ProcessingRetryableError,
)
from event_driven_document_processor.modules.documents.application.processing_service import (
    ProcessingService,
)


def test_processing_factory_is_lazy_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    processing.get_processing_service.cache_clear()
    monkeypatch.setattr(processing, "get_settings", lambda: Settings())
    dynamodb, s3 = Mock(), Mock()
    ddb_factory, s3_factory = Mock(return_value=dynamodb), Mock(return_value=s3)
    monkeypatch.setattr(processing, "create_dynamodb_client", ddb_factory)
    monkeypatch.setattr(processing, "create_s3_client", s3_factory)
    try:
        service = processing.get_processing_service()
        assert isinstance(service, ProcessingService)
        assert service is processing.get_processing_service()
        ddb_factory.assert_called_once()
        s3_factory.assert_called_once()
    finally:
        processing.get_processing_service.cache_clear()


def test_partial_factory_failure_closes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    processing.get_processing_service.cache_clear()
    dynamodb = Mock()
    monkeypatch.setattr(processing, "get_settings", lambda: Settings())
    monkeypatch.setattr(processing, "create_dynamodb_client", lambda _: dynamodb)
    monkeypatch.setattr(processing, "create_s3_client", Mock(side_effect=NoCredentialsError()))
    with pytest.raises(ProcessingRetryableError):
        processing.get_processing_service()
    dynamodb.close.assert_called_once()


@pytest.mark.parametrize(
    "change",
    [
        {"processing_max_file_size_bytes": 0},
        {"processing_max_image_pixels": 40_000_001},
        {"processing_max_image_dimension": 0},
        {"processing_max_pdf_pages": 0},
        {"processing_max_pdf_objects": 0},
        {"processing_lease_seconds": 30},
        {"processing_validation_timeout_seconds": 0},
    ],
)
def test_invalid_processing_budgets(change: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(**change)
