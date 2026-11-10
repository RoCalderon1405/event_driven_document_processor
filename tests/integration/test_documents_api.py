from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from event_driven_document_processor.modules.documents.domain.enums import DocumentStatus
from event_driven_document_processor.modules.documents.domain.processing import (
    FailureCode,
    ProcessingMetadata,
)


def test_create_and_retrieve_job(client):
    create = client.post(
        "/api/v1/documents",
        json={
            "filename": "contract.pdf",
            "content_type": "application/pdf",
            "description": "Sample contract",
        },
    )
    assert create.status_code == 201
    body = create.json()
    UUID(body["job_id"])
    assert body["status"] == "PENDING"
    assert body["filename"] == "contract.pdf"
    assert body["description"] == "Sample contract"
    assert body["created_at"]

    read = client.get(f"/api/v1/documents/{body['job_id']}")
    assert read.status_code == 200
    assert read.json() == body


def test_old_file_name_property_remains_supported(client):
    response = client.post(
        "/api/v1/documents",
        json={"file_name": "image.png", "content_type": "image/png"},
    )
    assert response.status_code == 201
    assert response.json()["filename"] == "image.png"


def test_invalid_mime_type_returns_422(client):
    response = client.post(
        "/api/v1/documents",
        json={"filename": "contract.pdf", "content_type": "application/exe"},
    )
    assert response.status_code == 422


def test_empty_filename_returns_422(client):
    response = client.post(
        "/api/v1/documents",
        json={"filename": "", "content_type": "application/pdf"},
    )
    assert response.status_code == 422


def test_missing_jobs_return_404_and_malformed_ids_return_422(client):
    assert client.get(f"/api/v1/documents/{uuid4()}").status_code == 404
    assert client.get("/api/v1/documents/not-a-uuid").status_code == 422


def test_pending_job_reports_no_processing_results(client):
    created = client.post(
        "/api/v1/documents",
        json={"filename": "contract.pdf", "content_type": "application/pdf"},
    ).json()
    body = client.get(f"/api/v1/documents/{created['job_id']}").json()
    # Backward compatibility: every pre-existing field is unchanged, plus the new
    # optional `processing` key which is null until an attempt records results.
    assert set(body) == {
        "job_id",
        "filename",
        "content_type",
        "description",
        "status",
        "created_at",
        "processing",
    }
    assert body["processing"] is None
    assert body["status"] == "PENDING"


def _finish_job(repository, job_id: UUID, *, status: DocumentStatus, processing):
    """Persist a terminal snapshot the way the processing store leaves it."""
    stored = repository.get(job_id)
    assert stored is not None
    repository.save(replace(stored, status=status, processing=processing))


def test_completed_job_exposes_safe_processing_results(client, repository):
    created = client.post(
        "/api/v1/documents",
        json={"filename": "contract.pdf", "content_type": "application/pdf"},
    ).json()
    started = datetime.now(UTC)
    _finish_job(
        repository,
        UUID(created["job_id"]),
        status=DocumentStatus.COMPLETED,
        processing=ProcessingMetadata(
            version_id="version-1",
            token="private-token",
            started_at=started,
            lease_expires_at=started + timedelta(seconds=180),
            finished_at=started + timedelta(seconds=3),
            sha256="a" * 64,
            size_bytes=2048,
        ),
    )

    body = client.get(f"/api/v1/documents/{created['job_id']}").json()

    assert body["status"] == "COMPLETED"
    result = body["processing"]
    assert set(result) == {"started_at", "finished_at", "sha256", "size_bytes", "failure_code"}
    assert result["sha256"] == "a" * 64
    assert result["size_bytes"] == 2048
    assert result["failure_code"] is None
    assert datetime.fromisoformat(result["finished_at"]) >= datetime.fromisoformat(
        result["started_at"]
    )
    # Internal fencing facts never reach the public response.
    assert "private-token" not in str(body)
    assert "version-1" not in str(body)


def test_failed_job_exposes_only_the_failure_reason(client, repository):
    created = client.post(
        "/api/v1/documents",
        json={"filename": "broken.pdf", "content_type": "application/pdf"},
    ).json()
    started = datetime.now(UTC)
    _finish_job(
        repository,
        UUID(created["job_id"]),
        status=DocumentStatus.FAILED,
        processing=ProcessingMetadata(
            version_id="version-2",
            token="private-token",
            started_at=started,
            lease_expires_at=started + timedelta(seconds=180),
            finished_at=started + timedelta(seconds=1),
            failure_code=FailureCode.INVALID_FORMAT,
        ),
    )

    result = client.get(f"/api/v1/documents/{created['job_id']}").json()["processing"]

    assert result["failure_code"] == "INVALID_FORMAT"
    # Failures must not carry completion facts, mirroring the processing store.
    assert result["sha256"] is None
    assert result["size_bytes"] is None
    assert datetime.fromisoformat(result["finished_at"])


def test_health_route(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
