"""Inspect real boto3-generated POST policies without making network requests."""

import base64
import json
from collections.abc import Iterator
from uuid import uuid4

import pytest
from botocore.exceptions import NoCredentialsError
from mypy_boto3_s3 import S3Client

from event_driven_document_processor.bootstrap.aws import create_s3_client
from event_driven_document_processor.bootstrap.settings import Settings
from event_driven_document_processor.modules.documents.application.errors import (
    UploadAuthorizationUnavailableError,
)
from event_driven_document_processor.modules.documents.infrastructure.s3_upload_authorizer import (
    S3UploadAuthorizer,
)


@pytest.fixture
def s3_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[S3Client]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    client = create_s3_client(Settings(s3_public_endpoint_url="http://localhost:4566"), public=True)
    yield client
    client.close()


def test_exact_policy_and_unique_server_keys(s3_client: S3Client) -> None:
    job_id = uuid4()
    signer = S3UploadAuthorizer(s3_client, "test-uploads", 300)
    first = signer.authorize(job_id, content_type="application/pdf", file_size_bytes=123)
    second = signer.authorize(job_id, content_type="application/pdf", file_size_bytes=123)
    assert first.object_reference.key.startswith(f"quarantine/{job_id}/")
    assert first.object_reference != second.object_reference
    assert first.url == "http://localhost:4566/test-uploads"
    assert s3_client.meta.config.signature_version == "s3v4"
    assert s3_client.meta.config.connect_timeout == 2
    assert s3_client.meta.config.read_timeout == 3
    policy = json.loads(base64.b64decode(first.fields["policy"]))
    assert {"key": first.object_reference.key} in policy["conditions"]
    assert {"bucket": "test-uploads"} in policy["conditions"]
    assert {"Content-Type": "application/pdf"} in policy["conditions"]
    assert ["content-length-range", 123, 123] in policy["conditions"]
    assert first.fields["x-amz-algorithm"] == "AWS4-HMAC-SHA256"
    assert first.fields["policy"] not in repr(first)


def test_signing_failure_does_not_log_material(
    s3_client: S3Client,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(**kwargs) -> None:
        raise NoCredentialsError()

    monkeypatch.setattr(s3_client, "generate_presigned_post", fail)
    with pytest.raises(UploadAuthorizationUnavailableError):
        S3UploadAuthorizer(s3_client, "test-uploads", 300).authorize(
            uuid4(),
            content_type="application/pdf",
            file_size_bytes=123,
        )
    assert "NoCredentialsError" in caplog.text
    assert "policy" not in caplog.text.lower()
    assert "localhost" not in caplog.text


def test_local_signer_requires_explicit_public_endpoint() -> None:
    with pytest.raises(ValueError, match="public S3 endpoint"):
        create_s3_client(
            Settings(aws_endpoint_url="http://floci:4566", s3_public_endpoint_url=None),
            public=True,
        )


@pytest.mark.parametrize(
    "origins",
    [
        ("*",),
        ("https://*.example.com",),
        ("http://localhost:3000/path",),
        ("http://user:pass@host",),
        ("http://localhost:3000?",),
        ("http://localhost:3000#",),
    ],
)
def test_cors_rejects_wildcard_or_non_origin(origins: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        Settings(s3_cors_allowed_origins=origins)


def test_cors_defaults_closed() -> None:
    assert Settings().s3_cors_allowed_origins == ()
    assert Settings(s3_cors_allowed_origins=("http://localhost:3000",)).s3_cors_allowed_origins


@pytest.mark.parametrize(
    "field,value",
    [
        ("upload_expires_in_seconds", 0),
        ("upload_expires_in_seconds", 901),
        ("upload_max_file_size_bytes", 0),
        ("upload_allowed_content_types", ()),
        ("upload_allowed_content_types", ("application/exe",)),
    ],
)
def test_invalid_upload_configuration(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        Settings(**{field: value})
