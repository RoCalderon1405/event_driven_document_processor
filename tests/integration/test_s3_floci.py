"""Real HTTP form uploads with S3 signature/authorization enforcement left enabled."""

import base64
import json
import os
import runpy
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from mypy_boto3_dynamodb import DynamoDBClient
from mypy_boto3_s3 import S3Client

from event_driven_document_processor.bootstrap.aws import create_dynamodb_client, create_s3_client
from event_driven_document_processor.bootstrap.dependencies import (
    get_document_repository,
    get_upload_authorizer,
)
from event_driven_document_processor.bootstrap.settings import Settings
from event_driven_document_processor.main import app
from event_driven_document_processor.modules.documents.infrastructure.dynamodb_repository import (
    DynamoDBJobRepository,
)
from event_driven_document_processor.modules.documents.infrastructure.s3_upload_authorizer import (
    S3UploadAuthorizer,
)

pytestmark = [
    pytest.mark.floci,
    pytest.mark.skipif(
        os.getenv("RUN_FLOCI_TESTS") != "1",
        reason="Set RUN_FLOCI_TESTS=1 for Floci",
    ),
]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def upload_store() -> Iterator[tuple[S3Client, DynamoDBClient, str, str]]:
    settings = Settings()
    for endpoint in (settings.s3_internal_endpoint_url, settings.s3_public_endpoint_url):
        if endpoint is None or endpoint.host not in {"localhost", "127.0.0.1", "floci"}:
            pytest.fail("S3 tests require explicit local endpoints")
    s3 = create_s3_client(settings)
    dynamodb = create_dynamodb_client(settings)
    suffix = uuid4().hex
    bucket, table = f"document-uploads-test-{suffix}", f"document-jobs-test-{suffix}"
    ensure_table = runpy.run_path(str(ROOT / "infra/local/init_dynamodb.py"))["ensure_table"]
    ensure_bucket = runpy.run_path(str(ROOT / "infra/local/init_s3.py"))["ensure_bucket"]
    table_ready = bucket_ready = False
    try:
        ensure_table(dynamodb, table)
        table_ready = True
        ensure_bucket(s3, bucket, settings.aws_default_region)
        bucket_ready = True
        ensure_bucket(s3, bucket, settings.aws_default_region)
        yield s3, dynamodb, bucket, table
    finally:
        try:
            if bucket_ready:
                for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
                    for item in page.get("Versions", []) + page.get("DeleteMarkers", []):
                        s3.delete_object(
                            Bucket=bucket, Key=item["Key"], VersionId=item["VersionId"]
                        )
                s3.delete_bucket(Bucket=bucket)
            if table_ready:
                dynamodb.delete_table(TableName=table)
        finally:
            s3.close()
            dynamodb.close()


@pytest.fixture
def upload_http(upload_store: tuple[S3Client, DynamoDBClient, str, str]) -> Iterator[TestClient]:
    _, dynamodb, bucket, table = upload_store
    signer_client = create_s3_client(Settings(), public=True)
    app.dependency_overrides[get_document_repository] = lambda: DynamoDBJobRepository(
        dynamodb,
        table,
    )
    app.dependency_overrides[get_upload_authorizer] = lambda: S3UploadAuthorizer(
        signer_client,
        bucket,
        300,
    )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        signer_client.close()


def issue(client: TestClient, size: int = 4, content_type: str = "application/pdf") -> dict:
    response = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "display.pdf",
            "content_type": content_type,
            "file_size_bytes": size,
        },
    )
    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()


def post_file(upload: dict, data: bytes = b"test", fields: dict | None = None) -> httpx.Response:
    """Use the returned URL verbatim; let httpx build multipart boundaries and length."""
    return httpx.post(
        upload["url"],
        data=upload["fields"] if fields is None else fields,
        files={"file": ("client-name.pdf", data, "application/octet-stream")},
        timeout=10,
        trust_env=False,
    )


@pytest.mark.parametrize("content_type", ["application/pdf", "image/png", "image/jpeg"])
def test_valid_upload_persists_reference_and_untrusted_bytes(
    upload_http: TestClient,
    upload_store: tuple[S3Client, DynamoDBClient, str, str],
    content_type: str,
) -> None:
    s3, dynamodb, bucket, table = upload_store
    result = issue(upload_http, content_type=content_type)
    upload, job = result["upload"], result["job"]
    assert post_file(upload).status_code == 204
    stored = DynamoDBJobRepository(dynamodb, table).get(UUID(job["job_id"]))
    assert stored.object_reference.bucket == bucket
    assert stored.object_reference.key == upload["fields"]["key"]
    raw = dynamodb.get_item(TableName=table, Key={"pk": {"S": f"JOB#{job['job_id']}"}})["Item"]
    assert "policy" not in json.dumps(raw)
    assert "signature" not in json.dumps(raw)
    response = s3.get_object(Bucket=bucket, Key=stored.object_reference.key)
    with response["Body"] as body:
        assert body.read() == b"test"  # MIME metadata is deliberately not proof of file bytes.
    assert response["ContentType"] == content_type
    assert upload_http.get(f"/api/v1/documents/{job['job_id']}").json() == job
    assert job["status"] == "PENDING"
    ensure_bucket = runpy.run_path(str(ROOT / "infra/local/init_s3.py"))["ensure_bucket"]
    ensure_bucket(s3, bucket, Settings().aws_default_region)
    assert s3.head_object(Bucket=bucket, Key=stored.object_reference.key)["ContentLength"] == 4


@pytest.mark.parametrize("data", [b"abc", b"abcde"])
def test_signed_exact_size_is_enforced(upload_http: TestClient, data: bytes) -> None:
    result = issue(upload_http)
    response = post_file(result["upload"], data)
    assert response.status_code == 400
    assert "EntityTooSmall" in response.text or "EntityTooLarge" in response.text


@pytest.mark.parametrize("field", ["key", "Content-Type", "x-amz-signature", "policy"])
def test_changed_fields_and_signatures_are_rejected(upload_http: TestClient, field: str) -> None:
    upload = issue(upload_http)["upload"]
    fields = dict(upload["fields"])
    if field == "key":
        fields[field] += "-changed"
    elif field == "Content-Type":
        fields[field] = "image/jpeg"
    elif field == "x-amz-signature":
        fields[field] = "0" * 64
    else:
        policy = json.loads(base64.b64decode(fields["policy"]))
        policy["conditions"].append(["starts-with", "$key", ""])
        fields[field] = base64.b64encode(json.dumps(policy).encode()).decode()
    assert post_file(upload, fields=fields).status_code == 403


def test_expired_authorization_rejected(
    upload_http: TestClient,
    upload_store: tuple[S3Client, DynamoDBClient, str, str],
) -> None:
    s3, _, bucket, _ = upload_store
    app.dependency_overrides[get_upload_authorizer] = lambda: S3UploadAuthorizer(s3, bucket, 1)
    upload = issue(upload_http)["upload"]
    time.sleep(2)
    assert post_file(upload).status_code == 403


def test_unsigned_upload_and_anonymous_read_denied(upload_http: TestClient) -> None:
    upload = issue(upload_http)["upload"]
    assert post_file(upload).status_code == 204
    assert post_file(upload, fields={"key": upload["fields"]["key"]}).status_code == 403
    with httpx.Client(timeout=10, trust_env=False) as http:
        object_url = f"{upload['url']}/{upload['fields']['key']}"
        assert http.get(object_url).status_code == 403
        assert http.head(object_url).status_code == 403
        assert http.put(object_url, content=b"evil").status_code == 403


def test_presigned_post_is_replayable_until_expiry(
    upload_http: TestClient,
    upload_store: tuple[S3Client, DynamoDBClient, str, str],
) -> None:
    s3, _, bucket, _ = upload_store
    upload = issue(upload_http)["upload"]
    assert post_file(upload, b"one!").status_code == 204
    assert post_file(upload, b"two!").status_code == 204
    response = s3.get_object(Bucket=bucket, Key=upload["fields"]["key"])
    with response["Body"] as body:
        assert body.read() == b"two!"


def test_bucket_security_and_empty_cors(
    upload_store: tuple[S3Client, DynamoDBClient, str, str],
) -> None:
    s3, _, bucket, _ = upload_store
    block = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
    assert all(block.values())
    assert s3.get_bucket_ownership_controls(Bucket=bucket)["OwnershipControls"]["Rules"] == [
        {"ObjectOwnership": "BucketOwnerEnforced"},
    ]
    rules = s3.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]["Rules"]
    assert rules[0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] == "AES256"
    with pytest.raises(ClientError) as cors:
        s3.get_bucket_cors(Bucket=bucket)
    assert cors.value.response["Error"]["Code"] == "NoSuchCORSConfiguration"
    with pytest.raises(ClientError) as policy:
        s3.get_bucket_policy(Bucket=bucket)
    assert policy.value.response["Error"]["Code"] == "NoSuchBucketPolicy"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Floci 2.4.0 stores bucket SSE config but omits SSE metadata for POST objects",
)
def test_post_object_reports_bucket_default_encryption(
    upload_http: TestClient,
    upload_store: tuple[S3Client, DynamoDBClient, str, str],
) -> None:
    """Keep the AWS expectation visible without claiming emulator encryption is verified."""
    s3, _, bucket, _ = upload_store
    upload = issue(upload_http)["upload"]
    post_file(upload).raise_for_status()
    metadata = s3.head_object(Bucket=bucket, Key=upload["fields"]["key"])
    assert metadata.get("ServerSideEncryption") == "AES256"
