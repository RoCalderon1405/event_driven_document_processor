"""Validate environment parsing and bounded AWS client configuration."""

import pytest
from pydantic import ValidationError

from event_driven_document_processor.bootstrap.aws import create_dynamodb_client
from event_driven_document_processor.bootstrap.settings import Settings


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://floci:4566")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("DYNAMODB_TABLE_NAME", "my-jobs")
    monkeypatch.setenv("AWS_MAX_ATTEMPTS", "2")
    settings = Settings()
    assert str(settings.aws_endpoint_url) == "http://floci:4566/"
    assert settings.aws_default_region == "eu-west-1"
    assert settings.dynamodb_table_name == "my-jobs"
    assert settings.aws_max_attempts == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("aws_endpoint_url", "not-a-url"),
        ("aws_connect_timeout", 0),
        ("aws_read_timeout", 31),
        ("aws_max_attempts", 0),
        ("aws_max_attempts", 6),
        ("dynamodb_table_name", "bad name"),
    ],
)
def test_invalid_settings(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_api_cors_defaults_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Browser API access stays disabled unless explicit origins are configured."""
    # Compare against library defaults, never against Compose or exported shell origins.
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("S3_CORS_ALLOWED_ORIGINS", raising=False)
    assert Settings().cors_allowed_origins == ()
    configured = Settings(cors_allowed_origins=("http://localhost:5173",))
    assert configured.cors_allowed_origins == ("http://localhost:5173",)


@pytest.mark.parametrize(
    "origins",
    [("*",), ("http://localhost:5173/",), ("http://user:pass@localhost:5173",)],
)
def test_api_cors_rejects_wildcard_or_degenerate_origins(origins: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        Settings(cors_allowed_origins=origins)


def test_client_has_bounded_sdk_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    settings = Settings(aws_endpoint_url="http://floci:4566", aws_max_attempts=2)
    client = create_dynamodb_client(settings)
    try:
        assert client.meta.config.connect_timeout == settings.aws_connect_timeout
        assert client.meta.config.read_timeout == settings.aws_read_timeout
        assert client.meta.config.retries == {"mode": "standard", "total_max_attempts": 2}
        assert client.meta.endpoint_url == "http://floci:4566/"
    finally:
        client.close()
