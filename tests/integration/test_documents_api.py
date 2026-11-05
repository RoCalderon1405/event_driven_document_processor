from uuid import UUID, uuid4


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


def test_health_route(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
