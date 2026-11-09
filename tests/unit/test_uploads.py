"""Upload use-case and HTTP contracts without AWS or Docker."""

from collections.abc import Iterator
from dataclasses import FrozenInstanceError, asdict
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from event_driven_document_processor.bootstrap.dependencies import (
    get_document_repository,
    get_upload_authorizer,
)
from event_driven_document_processor.main import app
from event_driven_document_processor.modules.documents.application.errors import (
    PersistenceUnavailableError,
    UploadAuthorizationUnavailableError,
    UploadValidationError,
)
from event_driven_document_processor.modules.documents.application.ports import (
    JobRepository,
    UploadAuthorizer,
)
from event_driven_document_processor.modules.documents.application.upload_models import (
    UploadAuthorization,
)
from event_driven_document_processor.modules.documents.application.upload_service import (
    UploadService,
)
from event_driven_document_processor.modules.documents.domain.models import S3ObjectReference
from event_driven_document_processor.modules.documents.infrastructure.in_memory_repository import (
    InMemoryJobRepository,
)


class FakeAuthorizer(UploadAuthorizer):
    """A deterministic signer for isolated application/HTTP tests."""

    def authorize(
        self,
        job_id: UUID,
        *,
        content_type: str,
        file_size_bytes: int,
    ) -> UploadAuthorization:
        return UploadAuthorization(
            S3ObjectReference("test-uploads", f"quarantine/{job_id}/opaque"),
            "http://localhost:4566/test-uploads",
            {"key": f"quarantine/{job_id}/opaque", "policy": "SECRET_POLICY"},
            300,
        )


@pytest.fixture(autouse=True)
def fake_signer() -> Iterator[None]:
    app.dependency_overrides[get_upload_authorizer] = FakeAuthorizer
    yield
    app.dependency_overrides.pop(get_upload_authorizer, None)


def make_service(
    repository: JobRepository | None = None,
    authorizer: UploadAuthorizer | None = None,
) -> UploadService:
    return UploadService(
        repository if repository is not None else InMemoryJobRepository(),
        authorizer if authorizer is not None else FakeAuthorizer(),
        allowed_content_types=("application/pdf", "image/png", "image/jpeg"),
        max_file_size_bytes=10 * 1024 * 1024,
    )


def test_only_reference_is_persisted() -> None:
    repository = InMemoryJobRepository()
    result = make_service(repository).create_upload_job(
        filename="a.pdf",
        content_type="application/pdf",
        file_size_bytes=123,
    )
    assert repository.get(result.job.job_id) == result.job
    assert result.job.object_reference == result.upload.object_reference
    assert result.job.status == "PENDING"
    assert "SECRET_POLICY" not in str(asdict(result.job))
    assert "SECRET_POLICY" not in repr(result)


@pytest.mark.parametrize(
    "change",
    [
        {"filename": "../a.pdf"},
        {"filename": "C:\\a.pdf"},
        {"filename": " "},
        {"filename": "bad\x00.pdf"},
        {"content_type": "application/exe"},
        {"file_size_bytes": 0},
        {"file_size_bytes": -1},
        {"file_size_bytes": True},
        {"file_size_bytes": "123"},
        {"file_size_bytes": 1.0},
        {"file_size_bytes": 10485761},
        {"description": "x" * 501},
    ],
)
def test_validation_precedes_signing(change: dict) -> None:
    signer = Mock(spec=UploadAuthorizer)
    repository = Mock()
    payload = {"filename": "a.pdf", "content_type": "application/pdf", "file_size_bytes": 123}
    payload.update(change)
    with pytest.raises(UploadValidationError):
        make_service(repository, signer).create_upload_job(**payload)
    signer.authorize.assert_not_called()
    repository.save.assert_not_called()


def test_persistence_failure_never_returns_authorization() -> None:
    repository = Mock()
    repository.save.side_effect = PersistenceUnavailableError("internal")
    with pytest.raises(PersistenceUnavailableError):
        make_service(repository).create_upload_job(
            filename="a.pdf",
            content_type="application/pdf",
            file_size_bytes=123,
        )


def test_signing_failure_does_not_save_a_job() -> None:
    repository = Mock()
    signer = Mock(spec=UploadAuthorizer)
    signer.authorize.side_effect = UploadAuthorizationUnavailableError("internal")
    with pytest.raises(UploadAuthorizationUnavailableError):
        make_service(repository, signer).create_upload_job(
            filename="a.pdf",
            content_type="application/pdf",
            file_size_bytes=123,
        )
    repository.save.assert_not_called()


def test_configured_mime_and_size_limits_are_applied() -> None:
    signer = Mock(spec=UploadAuthorizer)
    service = UploadService(
        InMemoryJobRepository(),
        signer,
        allowed_content_types=("image/png",),
        max_file_size_bytes=10,
    )
    for content_type, size in (("application/pdf", 1), ("image/png", 11)):
        with pytest.raises(UploadValidationError):
            service.create_upload_job(
                filename="a.png",
                content_type=content_type,
                file_size_bytes=size,
            )
    signer.authorize.assert_not_called()


def test_file_size_upper_boundary_and_immutable_reference() -> None:
    result = make_service().create_upload_job(
        filename="a.pdf",
        content_type="application/pdf",
        file_size_bytes=10485760,
    )
    with pytest.raises(FrozenInstanceError):
        result.job.object_reference.key = "changed"


def test_http_upload_and_original_get_contract(client: TestClient) -> None:
    response = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "file_size_bytes": 123,
        },
    )
    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["upload"]["method"] == "POST"
    assert body["upload"]["expires_in_seconds"] == 300
    assert set(body["job"]) == {
        "job_id",
        "filename",
        "content_type",
        "description",
        "status",
        "created_at",
    }
    assert client.get(f"/api/v1/documents/{body['job']['job_id']}").json() == body["job"]


@pytest.mark.parametrize("size", [0, -1, True, "12", 1.5, 10485761])
def test_http_strict_size(client: TestClient, size: object) -> None:
    response = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "file_size_bytes": size,
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("field", ["key", "bucket", "acl"])
def test_http_rejects_client_storage_controls(client: TestClient, field: str) -> None:
    response = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "file_size_bytes": 123,
            field: "malicious",
        },
    )
    assert response.status_code == 422


def test_http_signing_failure_is_sanitized(client: TestClient) -> None:
    signer = Mock(spec=UploadAuthorizer)
    signer.authorize.side_effect = UploadAuthorizationUnavailableError("SECRET_POLICY")
    app.dependency_overrides[get_upload_authorizer] = lambda: signer
    response = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "file_size_bytes": 123,
        },
    )
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {"detail": "Upload authorization temporarily unavailable"}


def test_http_storage_failure_contains_no_authorization(client: TestClient) -> None:
    repository = Mock()
    repository.save.side_effect = PersistenceUnavailableError("internal")
    app.dependency_overrides[get_document_repository] = lambda: repository
    response = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "file_size_bytes": 123,
        },
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Job storage temporarily unavailable"}
