"""Real version-pinned processing and deterministic competing DynamoDB updates in Floci."""

import hashlib
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import Mock
from uuid import uuid4

import pytest
from botocore.exceptions import EndpointConnectionError

from event_driven_document_processor.bootstrap.aws import create_dynamodb_client, create_s3_client
from event_driven_document_processor.bootstrap.settings import Settings
from event_driven_document_processor.modules.documents.application.processing_errors import (
    InvalidProcessingEventError,
    ProcessingRetryableError,
)
from event_driven_document_processor.modules.documents.application.processing_service import (
    ProcessingService,
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
from event_driven_document_processor.modules.documents.infrastructure.document_validator import (
    IsolatedDocumentValidator,
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

pytestmark = [
    pytest.mark.floci,
    pytest.mark.skipif(os.getenv("RUN_FLOCI_TESTS") != "1", reason="Set RUN_FLOCI_TESTS=1"),
]
NOW = datetime(2026, 11, 7, tzinfo=UTC)


@pytest.fixture
def processing_stack() -> Iterator[tuple]:
    """Provision only unique disposable resources, leaving development objects untouched."""
    settings = Settings()
    endpoint = settings.aws_endpoint_url
    if endpoint is None or endpoint.host not in {"localhost", "127.0.0.1", "floci"}:
        pytest.fail("Explicit local AWS_ENDPOINT_URL required")
    s3_endpoint = settings.s3_internal_endpoint_url
    if s3_endpoint is not None and s3_endpoint.host not in {"localhost", "127.0.0.1", "floci"}:
        pytest.fail("Explicit local S3 endpoint required")
    ddb = create_dynamodb_client(settings)
    s3 = create_s3_client(settings)
    table = f"processing-test-{uuid4().hex}"
    bucket = f"processing-test-{uuid4().hex}"
    table_created = bucket_created = False
    try:
        ddb.create_table(
            TableName=table,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table_created = True
        ddb.get_waiter("table_exists").wait(TableName=table)
        s3.create_bucket(Bucket=bucket)
        bucket_created = True
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        repository = DynamoDBJobRepository(ddb, table)
        store = DynamoDBProcessingStore(ddb, table)
        job = DocumentJob(
            uuid4(),
            "document.pdf",
            "application/pdf",
            None,
            DocumentStatus.PENDING,
            NOW,
            S3ObjectReference(bucket, f"quarantine/{uuid4()}/opaque"),
        )
        yield repository, store, s3, job, ddb, table
    finally:
        try:
            if bucket_created:
                for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
                    for version in page.get("Versions", []) + page.get("DeleteMarkers", []):
                        s3.delete_object(
                            Bucket=bucket, Key=version["Key"], VersionId=version["VersionId"]
                        )
                s3.delete_bucket(Bucket=bucket)
            if table_created:
                ddb.delete_table(TableName=table)
        finally:
            s3.close()
            ddb.close()


def upload(s3, job: DocumentJob, data: bytes) -> str:
    """Upload synthetic bytes to this fixture's private exact key."""
    return s3.put_object(
        Bucket=job.object_reference.bucket,
        Key=job.object_reference.key,
        Body=data,
        ContentType=job.content_type,
    )["VersionId"]


def service(repo, store, s3, **kwargs) -> ProcessingService:
    """Use the real shared application implementation, not an integration-only processor."""
    return ProcessingService(
        repo,
        store,
        S3ObjectReader(s3),
        IsolatedDocumentValidator(),
        max_file_size_bytes=kwargs.pop("max_file_size_bytes", 1024**2),
        clock=lambda: NOW,
        **kwargs,
    )


@pytest.mark.parametrize("mime", ["application/pdf", "image/png", "image/jpeg"])
def test_process_exact_older_version_and_idempotency(processing_stack, valid_documents, mime):
    repo, store, s3, job, ddb, table = processing_stack
    data = valid_documents[mime]
    job = replace(job, content_type=mime, declared_size_bytes=len(data))
    repo.save(job)
    version = upload(s3, job, data)
    later = upload(s3, job, b"new invalid overwrite")
    processor = service(repo, store, s3)
    assert processor.process(job.job_id, job.object_reference, version) == "COMPLETED"
    result = repo.get(job.job_id)
    assert result.processing.version_id == version
    assert result.processing.sha256 == hashlib.sha256(data).hexdigest()
    assert result.processing.size_bytes == len(data)
    assert processor.process(job.job_id, job.object_reference, version) == "ALREADY_TERMINAL"
    assert processor.process(job.job_id, job.object_reference, later) == "OTHER_VERSION"
    assert repo.get(job.job_id) == result
    assert ddb.scan(TableName=table)["Count"] == 1  # No HASH# deduplication side effects.


@pytest.mark.parametrize("mime", ["application/pdf", "image/png", "image/jpeg"])
@pytest.mark.parametrize("kind", ["truncated", "mismatch", "empty", "oversize", "declared_size"])
def test_permanent_failures(processing_stack, valid_documents, mime, kind):
    repo, store, s3, job, _, _ = processing_stack
    data = valid_documents[mime]
    declared = None
    limit = 1024**2
    expected = FailureCode.INVALID_FORMAT
    if kind == "truncated":
        data = data[:-15]
    elif kind == "mismatch":
        data = valid_documents["image/png" if mime == "application/pdf" else "application/pdf"]
        expected = FailureCode.FORMAT_MISMATCH
    elif kind == "empty":
        data = b""
        expected = FailureCode.EMPTY
    elif kind == "oversize":
        limit = 10
        expected = FailureCode.TOO_LARGE
    else:
        declared = len(data) + 1
        expected = FailureCode.SIZE_MISMATCH
    job = replace(job, content_type=mime, declared_size_bytes=declared)
    repo.save(job)
    version = upload(s3, job, data)
    assert (
        service(repo, store, s3, max_file_size_bytes=limit).process(
            job.job_id,
            job.object_reference,
            version,
        )
        == "FAILED"
    )
    result = repo.get(job.job_id)
    assert result.processing.failure_code == expected
    assert result.processing.sha256 is None


@pytest.mark.parametrize("same_version", [True, False])
def test_concurrent_claims_one_winner(processing_stack, same_version):
    repo, store, _, job, _, _ = processing_stack
    repo.save(job)
    barrier = Barrier(2)

    def attempt(version: str) -> tuple[bool, ProcessingMetadata]:
        claim = ProcessingMetadata(version, str(uuid4()), NOW, NOW + timedelta(seconds=10))
        barrier.wait(timeout=10)
        return store.claim(job, claim, NOW), claim

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["v1", "v1" if same_version else "v2"]))
    assert sorted(won for won, _ in results) == [False, True]
    winning = next(claim for won, claim in results if won)
    assert repo.get(job.job_id).processing == winning
    assert not store.claim(job, replace(winning, token="duplicate"), NOW)


def test_expiry_recovery_and_stale_worker_fencing(processing_stack):
    repo, store, _, job, _, _ = processing_stack
    repo.save(job)
    first = ProcessingMetadata("v1", "old", NOW, NOW + timedelta(seconds=10))
    assert store.claim(job, first, NOW)
    expired = NOW + timedelta(seconds=10)
    second = ProcessingMetadata("v1", "new", expired, expired + timedelta(seconds=10))
    assert not store.finish(job.job_id, first, expired, failure_code=FailureCode.EMPTY)
    assert not store.claim(job, replace(second, version_id="v2"), expired)
    assert store.claim(job, second, expired)
    assert not store.finish(job.job_id, first, expired, sha256="a" * 64, size_bytes=1)
    assert not store.finish(job.job_id, first, expired, failure_code=FailureCode.EMPTY)
    assert store.finish(job.job_id, second, expired, sha256="b" * 64, size_bytes=2)
    assert not store.finish(job.job_id, second, expired, failure_code=FailureCode.EMPTY)
    assert not store.claim(
        job,
        replace(second, token="late", lease_expires_at=expired + timedelta(seconds=40)),
        expired + timedelta(seconds=20),
    )
    result = repo.get(job.job_id)
    assert result.status == DocumentStatus.COMPLETED
    assert result.processing.token == "new" and result.processing.sha256 == "b" * 64


def test_read_failure_then_same_version_recovery(processing_stack, valid_documents):
    repo, store, s3, job, _, _ = processing_stack
    repo.save(job)
    version = upload(s3, job, valid_documents["application/pdf"])
    processor = service(repo, store, s3)
    # A missing exact version must never read the existing latest object instead.
    with pytest.raises(ProcessingRetryableError):
        processor.process(job.job_id, job.object_reference, "missing-version")
    stuck = repo.get(job.job_id)
    assert stuck.status == DocumentStatus.PROCESSING
    assert stuck.processing.failure_code is None
    assert processor.process(job.job_id, job.object_reference, version) == "OTHER_VERSION"
    # A simulated crashed attempt on a valid selected version can recover after expiry.
    other = replace(job, job_id=uuid4())
    repo.save(other)
    claim = ProcessingMetadata(version, "crashed", NOW - timedelta(seconds=200), NOW)
    assert store.claim(other, claim, NOW - timedelta(seconds=200))
    assert processor.process(other.job_id, other.object_reference, version) == "COMPLETED"


def test_mismatch_missing_and_legacy_records(processing_stack):
    repo, store, s3, job, ddb, table = processing_stack
    repo.save(job)
    processor = service(repo, store, s3)
    with pytest.raises(InvalidProcessingEventError):
        processor.process(job.job_id, replace(job.object_reference, key="different"), "v1")
    assert repo.get(job.job_id).status == DocumentStatus.PENDING
    assert not store.claim(
        replace(job, object_reference=replace(job.object_reference, bucket="bad")),
        ProcessingMetadata("v1", "x", NOW, NOW + timedelta(seconds=10)),
        NOW,
    )
    legacy = replace(job, job_id=uuid4(), object_reference=None)
    repo.save(legacy)
    assert repo.get(legacy.job_id) == legacy
    raw = ddb.get_item(TableName=table, Key={"pk": {"S": f"JOB#{legacy.job_id}"}})["Item"]
    assert "processing" not in raw and "declared_size_bytes" not in raw
    with pytest.raises(InvalidProcessingEventError):
        processor.process(legacy.job_id, job.object_reference, "v1")
    missing = replace(job, job_id=uuid4())
    assert not store.claim(
        missing, ProcessingMetadata("v1", "x", NOW, NOW + timedelta(seconds=10)), NOW
    )


def test_transient_s3_failure_recovers_selected_version(
    processing_stack,
    valid_documents,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, store, s3, job, _, _ = processing_stack
    repo.save(job)
    version = upload(s3, job, valid_documents["application/pdf"])
    processor = service(repo, store, s3)
    original = s3.get_object
    monkeypatch.setattr(
        s3,
        "get_object",
        Mock(
            side_effect=EndpointConnectionError(
                endpoint_url="http://floci:4566",
            )
        ),
    )
    with pytest.raises(ProcessingRetryableError):
        processor.process(job.job_id, job.object_reference, version)
    first = repo.get(job.job_id)
    assert first.status == DocumentStatus.PROCESSING
    assert first.processing.version_id == version and first.processing.failure_code is None
    with pytest.raises(ProcessingRetryableError):
        processor.process(job.job_id, job.object_reference, version)
    monkeypatch.setattr(s3, "get_object", original)
    processor._clock = lambda: NOW + timedelta(seconds=181)
    assert processor.process(job.job_id, job.object_reference, version) == "COMPLETED"
    assert repo.get(job.job_id).processing.token != first.processing.token


def test_concurrent_expired_claim_recovery_has_one_winner(processing_stack):
    repo, store, _, job, _, _ = processing_stack
    repo.save(job)
    first = ProcessingMetadata("v1", "crashed", NOW, NOW + timedelta(seconds=10))
    assert store.claim(job, first, NOW)
    recovery_time = NOW + timedelta(seconds=10)
    barrier = Barrier(2)

    def recover(token: str) -> bool:
        claim = ProcessingMetadata(
            "v1", token, recovery_time, recovery_time + timedelta(seconds=10)
        )
        barrier.wait(timeout=10)
        return store.claim(job, claim, recovery_time)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(recover, ["new-a", "new-b"])) == [False, True]
    assert repo.get(job.job_id).processing.token in {"new-a", "new-b"}
