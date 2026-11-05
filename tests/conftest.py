import pytest
from fastapi.testclient import TestClient

from event_driven_document_processor.bootstrap.dependencies import get_document_repository
from event_driven_document_processor.main import app
from event_driven_document_processor.modules.documents.infrastructure.in_memory_repository import (
    InMemoryJobRepository,
)


@pytest.fixture
def client():
    repository = InMemoryJobRepository()
    app.dependency_overrides[get_document_repository] = lambda: repository
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
