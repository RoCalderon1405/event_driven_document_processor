"""Boundary failures, exact-version streaming, and additive internal serialization."""

import io
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.response import StreamingBody

from event_driven_document_processor.modules.documents.application.errors import (
    PersistenceDataError,
    PersistenceUnavailableError,
)
from event_driven_document_processor.modules.documents.application.processing_errors import (
    ProcessingRetryableError,
)
from event_driven_document_processor.modules.documents.domain.enums import DocumentStatus
from event_driven_document_processor.modules.documents.domain.models import (
    DocumentJob,
    S3ObjectReference,
)
from event_driven_document_processor.modules.documents.domain.processing import (
    FailureCode,
    ProcessingMetadata,
)
from event_driven_document_processor.modules.documents.infrastructure.dynamodb_repository import (
    DynamoDBJobRepository,
)
from event_driven_document_processor.modules.documents.infrastructure.processing_store import (
    DynamoDBProcessingStore,
)
from event_driven_document_processor.modules.documents.infrastructure.s3_object_reader import (
    S3ObjectReader,
)

NOW = datetime(2026, 11, 7, tzinfo=UTC)
REFERENCE = S3ObjectReference("bucket", "quarantine/key")


@pytest.fixture
def job() -> DocumentJob:
    return DocumentJob(
        uuid4(), "file.pdf", "application/pdf", None, DocumentStatus.PENDING, NOW, REFERENCE
    )


def test_internal_and_legacy_roundtrip(job: DocumentJob):
    sdk = Mock()
    repo = DynamoDBJobRepository(sdk, "jobs")
    repo.save(job)
    legacy_item = sdk.put_item.call_args.kwargs["Item"]
    sdk.get_item.return_value = {"Item": legacy_item}
    assert repo.get(job.job_id) == job
    metadata = ProcessingMetadata(
        "v1",
        "token",
        NOW,
        NOW + timedelta(seconds=180),
        NOW + timedelta(seconds=1),
        "a" * 64,
        123,
        None,
    )
    internal = replace(
        job, declared_size_bytes=123, processing=metadata, status=DocumentStatus.COMPLETED
    )
    repo.save(internal)
    sdk.get_item.return_value = {"Item": sdk.put_item.call_args.kwargs["Item"]}
    assert repo.get(job.job_id) == internal
    failed = replace(
        internal,
        processing=replace(
            metadata, sha256=None, size_bytes=None, failure_code=FailureCode.INVALID_FORMAT
        ),
    )
    repo.save(failed)
    sdk.get_item.return_value = {"Item": sdk.put_item.call_args.kwargs["Item"]}
    assert repo.get(job.job_id) == failed


@pytest.mark.parametrize("value", [{"NULL": True}, {"M": {}}, {"M": {"version_id": {"S": "v"}}}])
def test_corrupt_processing_is_not_legacy(job: DocumentJob, value):
    sdk = Mock()
    repo = DynamoDBJobRepository(sdk, "jobs")
    repo.save(job)
    item = sdk.put_item.call_args.kwargs["Item"]
    item["processing"] = value
    sdk.get_item.return_value = {"Item": item}
    with pytest.raises(PersistenceDataError):
        repo.get(job.job_id)


@pytest.mark.parametrize(
    "code", ["ConditionalCheckFailedException", "ThrottlingException", "network"]
)
@pytest.mark.parametrize("operation", ["claim", "finish"])
def test_update_failures_are_not_missing(job: DocumentJob, code: str, operation: str):
    sdk = Mock()
    sdk.update_item.side_effect = (
        EndpointConnectionError(endpoint_url="http://private")
        if code == "network"
        else ClientError({"Error": {"Code": code, "Message": "PRIVATE_PAYLOAD"}}, "UpdateItem")
    )
    store = DynamoDBProcessingStore(sdk, "jobs")
    metadata = ProcessingMetadata("v1", "token", NOW, NOW + timedelta(seconds=180))
    args = (job, metadata, NOW) if operation == "claim" else (job.job_id, metadata, NOW)
    if code == "ConditionalCheckFailedException":
        assert (
            getattr(store, operation)(
                *args, **({"failure_code": FailureCode.EMPTY} if operation == "finish" else {})
            )
            is False
        )
    else:
        with pytest.raises(PersistenceUnavailableError):
            getattr(store, operation)(
                *args, **({"failure_code": FailureCode.EMPTY} if operation == "finish" else {})
            )
    sdk.put_item.assert_not_called()


def test_conditional_expression_invariants(job: DocumentJob):
    sdk = Mock()
    store = DynamoDBProcessingStore(sdk, "jobs")
    metadata = ProcessingMetadata("v1", "token", NOW, NOW + timedelta(seconds=180))
    assert store.claim(job, metadata, NOW)
    request = sdk.update_item.call_args.kwargs
    assert "attribute_not_exists(#processing)" in request["ConditionExpression"]
    assert "#processing.version_id = :version" in request["ConditionExpression"]
    assert "#processing.lease_expires_at <= :now" in request["ConditionExpression"]
    assert "object_reference" in request["ConditionExpression"]
    assert store.finish(job.job_id, metadata, NOW, sha256="a" * 64, size_bytes=1)
    request = sdk.update_item.call_args.kwargs
    assert "#processing.#token = :token" in request["ConditionExpression"]
    assert "#processing.lease_expires_at > :now" in request["ConditionExpression"]


@pytest.mark.parametrize("mode", ["complete", "early_exit", "wrong_version", "truncated"])
def test_version_pinning_and_body_cleanup(mode: str):
    raw = io.BytesIO(b"a" * 100_000)
    body = StreamingBody(raw, 200_000 if mode == "truncated" else 100_000)
    sdk = Mock(
        get_object=Mock(
            return_value={"Body": body, "VersionId": "wrong" if mode == "wrong_version" else "v1"}
        )
    )
    reader = S3ObjectReader(sdk)
    if mode in {"wrong_version", "truncated"}:
        with pytest.raises(ProcessingRetryableError), reader.read(REFERENCE, "v1") as chunks:
            list(chunks)
    else:
        with reader.read(REFERENCE, "v1") as chunks:
            if mode == "early_exit":
                assert len(next(chunks)) == 65536
            else:
                values = list(chunks)
                assert b"".join(values) == b"a" * 100_000
                assert all(len(value) <= 65536 for value in values)
    assert raw.closed
    sdk.get_object.assert_called_once_with(
        Bucket=REFERENCE.bucket, Key=REFERENCE.key, VersionId="v1"
    )


@pytest.mark.parametrize("code", ["NoSuchVersion", "AccessDenied", "SlowDown"])
def test_s3_failure_never_falls_back_to_latest(code: str):
    sdk = Mock()
    sdk.get_object.side_effect = ClientError({"Error": {"Code": code}}, "GetObject")
    with pytest.raises(ProcessingRetryableError), S3ObjectReader(sdk).read(REFERENCE, "v1"):
        pass
    assert sdk.get_object.call_count == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("declared_size_bytes", {"N": "-1"}),
        ("declared_size_bytes", {"N": "1.5"}),
        ("processing", {"M": {"version_id": {"S": "null"}}}),
    ],
)
def test_corrupt_new_attributes_are_explicit(job: DocumentJob, field: str, value: dict):
    sdk = Mock()
    repo = DynamoDBJobRepository(sdk, "jobs")
    repo.save(job)
    item = sdk.put_item.call_args.kwargs["Item"]
    item[field] = value
    sdk.get_item.return_value = {"Item": item}
    with pytest.raises(PersistenceDataError):
        repo.get(job.job_id)
