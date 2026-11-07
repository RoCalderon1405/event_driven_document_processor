"""Persistence failures must not leak SDK details or masquerade as a 404."""

from uuid import uuid4

import pytest
from botocore.exceptions import NoRegionError
from fastapi.testclient import TestClient

from event_driven_document_processor.bootstrap import dependencies
from event_driven_document_processor.bootstrap.dependencies import get_document_repository
from event_driven_document_processor.main import app
from event_driven_document_processor.modules.documents.application.errors import (
    PersistenceDataError,
    PersistenceUnavailableError,
)
from event_driven_document_processor.modules.documents.infrastructure.in_memory_repository import (
    InMemoryJobRepository,
)


@pytest.mark.parametrize(
    "error,status,detail",
    [
        (PersistenceUnavailableError, 503, "Job storage temporarily unavailable"),
        (PersistenceDataError, 500, "Unable to retrieve document job"),
    ],
)
@pytest.mark.parametrize("method", ["get", "post"])
def test_sanitized_storage_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: type[Exception],
    status: int,
    detail: str,
    method: str,
) -> None:
    def fail(*args, **kwargs):
        raise error("SECRET internal SDK endpoint")

    repository = InMemoryJobRepository()
    monkeypatch.setattr(repository, "get", fail)
    monkeypatch.setattr(repository, "save", fail)
    app.dependency_overrides[get_document_repository] = lambda: repository
    if method == "get":
        response = client.get(f"/api/v1/documents/{uuid4()}")
    else:
        response = client.post(
            "/api/v1/documents",
            json={
                "filename": "a.pdf",
                "content_type": "application/pdf",
            },
        )
    assert response.status_code == status
    assert response.json() == {"detail": detail}


def test_client_construction_failure_is_sanitized(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fail(settings) -> None:
        raise NoRegionError()

    dependencies.get_document_repository.cache_clear()
    app.dependency_overrides.pop(get_document_repository)
    monkeypatch.setattr(dependencies, "create_dynamodb_client", fail)
    try:
        response = client.get(f"/api/v1/documents/{uuid4()}")
        assert response.status_code == 503
        assert response.json() == {"detail": "Job storage temporarily unavailable"}
        assert "NoRegionError" in caplog.text
    finally:
        dependencies.get_document_repository.cache_clear()
