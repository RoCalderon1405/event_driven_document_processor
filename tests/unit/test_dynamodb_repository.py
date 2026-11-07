"""Exercise SDK requests and failures without a network or running emulator."""

import logging
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber
from mypy_boto3_dynamodb import DynamoDBClient

from event_driven_document_processor.modules.documents.application.errors import (
    PersistenceDataError,
    PersistenceUnavailableError,
)
from event_driven_document_processor.modules.documents.domain.enums import DocumentStatus
from event_driven_document_processor.modules.documents.domain.models import DocumentJob
from event_driven_document_processor.modules.documents.infrastructure.dynamodb_repository import (
    DynamoDBJobRepository,
)


@pytest.fixture
def aws_client() -> Iterator[DynamoDBClient]:
    client = boto3.client(
        "dynamodb",
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    yield client
    client.close()


@pytest.fixture
def job() -> DocumentJob:
    return DocumentJob(
        job_id=uuid4(),
        filename="contract.pdf",
        content_type="application/pdf",
        description=None,
        status=DocumentStatus.PENDING,
        created_at=datetime.now(UTC),
    )


def item_for(job: DocumentJob) -> dict[str, Any]:
    return {
        "pk": {"S": f"JOB#{job.job_id}"},
        "job_id": {"S": str(job.job_id)},
        "filename": {"S": job.filename},
        "content_type": {"S": job.content_type},
        "description": {"NULL": True} if job.description is None else {"S": job.description},
        "status": {"S": job.status.value},
        "created_at": {"S": job.created_at.isoformat()},
    }


@pytest.mark.parametrize("description", [None, "", "A document"])
def test_save_serializes_job(
    aws_client: DynamoDBClient,
    job: DocumentJob,
    description: str | None,
) -> None:
    job = replace(job, description=description)
    with Stubber(aws_client) as stub:
        stub.add_response("put_item", {}, {"TableName": "jobs", "Item": item_for(job)})
        DynamoDBJobRepository(aws_client, "jobs").save(job)
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("description", [None, "", "Résumé ✓"])
def test_get_reconstructs_job(
    aws_client: DynamoDBClient,
    job: DocumentJob,
    description: str | None,
) -> None:
    job = replace(job, description=description)
    with Stubber(aws_client) as stub:
        stub.add_response(
            "get_item",
            {"Item": item_for(job)},
            {
                "TableName": "jobs",
                "Key": {"pk": {"S": f"JOB#{job.job_id}"}},
                "ConsistentRead": True,
            },
        )
        assert DynamoDBJobRepository(aws_client, "jobs").get(job.job_id) == job
        stub.assert_no_pending_responses()


def test_get_missing(aws_client: DynamoDBClient, job: DocumentJob) -> None:
    with Stubber(aws_client) as stub:
        stub.add_response("get_item", {})
        assert DynamoDBJobRepository(aws_client, "jobs").get(job.job_id) is None


@pytest.mark.parametrize("operation", ["put_item", "get_item"])
@pytest.mark.parametrize(
    "code",
    [
        "AccessDeniedException",
        "ResourceNotFoundException",
        "ProvisionedThroughputExceededException",
    ],
)
def test_service_failure_is_not_missing(
    aws_client: DynamoDBClient,
    job: DocumentJob,
    operation: str,
    code: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with Stubber(aws_client) as stub:
        stub.add_client_error(operation, service_error_code=code, service_message="SECRET_PAYLOAD")
        repository = DynamoDBJobRepository(aws_client, "jobs")
        with caplog.at_level(logging.ERROR), pytest.raises(PersistenceUnavailableError):
            if operation == "put_item":
                repository.save(job)
            else:
                repository.get(job.job_id)
    assert code in caplog.text
    assert str(job.job_id) in caplog.text
    assert "SECRET_PAYLOAD" not in caplog.text


def test_connection_failure(
    aws_client: DynamoDBClient, job: DocumentJob, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(**kwargs: Any) -> None:
        raise EndpointConnectionError(endpoint_url="http://private-host")

    monkeypatch.setattr(aws_client, "get_item", fail)
    with pytest.raises(PersistenceUnavailableError):
        DynamoDBJobRepository(aws_client, "jobs").get(job.job_id)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", {"S": "UNKNOWN"}),
        ("created_at", {"S": "bad"}),
        ("created_at", {"S": "2026-01-01T00:00:00"}),
        ("filename", {"N": "1"}),
        ("job_id", {"S": str(uuid4())}),
        ("pk", {"S": "HASH#reserved"}),
        ("description", {"NULL": False}),
    ],
)
def test_corrupt_data_is_explicit(
    aws_client: DynamoDBClient,
    job: DocumentJob,
    field: str,
    value: dict[str, Any],
) -> None:
    item = item_for(job)
    item[field] = value
    with Stubber(aws_client) as stub:
        stub.add_response("get_item", {"Item": item})
        with pytest.raises(PersistenceDataError):
            DynamoDBJobRepository(aws_client, "jobs").get(job.job_id)


def test_missing_stored_attribute_is_explicit(aws_client: DynamoDBClient, job: DocumentJob) -> None:
    item = item_for(job)
    del item["filename"]
    with Stubber(aws_client) as stub:
        stub.add_response("get_item", {"Item": item})
        with pytest.raises(PersistenceDataError):
            DynamoDBJobRepository(aws_client, "jobs").get(job.job_id)
