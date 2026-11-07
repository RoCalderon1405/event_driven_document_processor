"""Explicitly opted-in tests against Floci, with isolated disposable tables."""

import os
import runpy
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from mypy_boto3_dynamodb import DynamoDBClient

from event_driven_document_processor.bootstrap.aws import create_dynamodb_client
from event_driven_document_processor.bootstrap.dependencies import get_document_repository
from event_driven_document_processor.bootstrap.settings import Settings
from event_driven_document_processor.main import app
from event_driven_document_processor.modules.documents.application.service import DocumentService
from event_driven_document_processor.modules.documents.infrastructure.dynamodb_repository import (
    DynamoDBJobRepository,
)

pytestmark = [
    pytest.mark.floci,
    pytest.mark.skipif(
        os.getenv("RUN_FLOCI_TESTS") != "1", reason="Set RUN_FLOCI_TESTS=1 for Floci"
    ),
]


@pytest.fixture
def store() -> Iterator[tuple[DynamoDBClient, str]]:
    settings = Settings()
    if settings.aws_endpoint_url is None or settings.aws_endpoint_url.host not in {
        "floci",
        "localhost",
        "127.0.0.1",
    }:
        pytest.fail("Floci tests require an explicit local AWS_ENDPOINT_URL")
    client = create_dynamodb_client(settings)
    table_name = f"document-jobs-test-{uuid4().hex}"
    ensure_table = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "infra/local/init_dynamodb.py")
    )["ensure_table"]
    initialized = False
    try:
        ensure_table(client, table_name)
        initialized = True
        ensure_table(client, table_name)
        yield client, table_name
    finally:
        # Delete only this fixture's unique table, never the configured development table.
        try:
            if initialized:
                client.delete_table(TableName=table_name)
        finally:
            client.close()


@pytest.mark.parametrize("description", [None, "", "Résumé ✓"])
def test_round_trip_across_repository_instances(
    store: tuple[DynamoDBClient, str], description: str | None
) -> None:
    client, table_name = store
    service = DocumentService(DynamoDBJobRepository(client, table_name))
    job = service.create_job(
        filename="contract.pdf",
        content_type="application/pdf",
        description=description,
    )
    other_client = create_dynamodb_client(Settings())
    try:
        other = DynamoDBJobRepository(other_client, table_name)
        assert other.get(job.job_id) == job
        assert other.get(uuid4()) is None
        raw = client.get_item(
            TableName=table_name,
            Key={"pk": {"S": f"JOB#{job.job_id}"}},
            ConsistentRead=True,
        )["Item"]
        assert raw["pk"] == {"S": f"JOB#{job.job_id}"}
    finally:
        other_client.close()


def test_http_contract_with_real_storage(store: tuple[DynamoDBClient, str]) -> None:
    sdk_client, table_name = store
    app.dependency_overrides[get_document_repository] = lambda: DynamoDBJobRepository(
        sdk_client, table_name
    )
    try:
        with TestClient(app) as http:
            response = http.post(
                "/api/v1/documents",
                json={
                    "file_name": "image.png",
                    "content_type": "image/png",
                },
            )
            assert response.status_code == 201
            body = response.json()
            assert body["filename"] == "image.png"
            assert body["status"] == "PENDING"
            assert body["description"] is None
            assert http.get(f"/api/v1/documents/{body['job_id']}").json() == body
            assert http.get(f"/api/v1/documents/{uuid4()}").status_code == 404
            assert http.get("/api/v1/documents/invalid").status_code == 422
    finally:
        app.dependency_overrides.clear()
