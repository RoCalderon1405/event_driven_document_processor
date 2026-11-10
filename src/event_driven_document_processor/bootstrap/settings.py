"""Environment-based runtime configuration; credentials stay in boto3's provider chain."""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validate infrastructure settings without contacting AWS at import time."""

    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    aws_endpoint_url: AnyHttpUrl | None = None
    aws_default_region: str = Field(default="us-east-1", min_length=1)
    dynamodb_table_name: str = Field(
        default="document-jobs", min_length=3, max_length=255, pattern=r"^[a-zA-Z0-9_.-]+$"
    )
    aws_connect_timeout: float = Field(default=2.0, gt=0, le=30)
    aws_read_timeout: float = Field(default=3.0, gt=0, le=30)
    aws_max_attempts: int = Field(default=3, ge=1, le=5)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # Browser origins allowed to call this API; empty keeps cross-origin access closed.
    cors_allowed_origins: tuple[str, ...] = ()
    s3_internal_endpoint_url: AnyHttpUrl | None = None
    s3_public_endpoint_url: AnyHttpUrl | None = None
    s3_bucket_name: str = Field(
        default="document-uploads",
        min_length=3,
        max_length=63,
        pattern=r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$",
    )
    upload_max_file_size_bytes: int = Field(default=10 * 1024 * 1024, gt=0, le=5 * 1024**3)
    upload_expires_in_seconds: int = Field(default=300, ge=1, le=900)
    upload_allowed_content_types: tuple[
        Literal["application/pdf", "image/png", "image/jpeg"], ...
    ] = Field(default=("application/pdf", "image/png", "image/jpeg"), min_length=1)
    s3_cors_allowed_origins: tuple[str, ...] = ()
    processing_max_file_size_bytes: int = Field(default=10 * 1024**2, gt=0, le=100 * 1024**2)
    processing_lease_seconds: int = Field(default=180, ge=30, le=3600)
    processing_read_timeout_seconds: float = Field(default=60, gt=0, le=120)
    processing_validation_timeout_seconds: float = Field(default=15, gt=0, le=60)
    processing_max_image_pixels: int = Field(default=20_000_000, gt=0, le=40_000_000)
    processing_max_image_dimension: int = Field(default=16_384, gt=0, le=32_768)
    processing_max_pdf_pages: int = Field(default=500, gt=0, le=2000)
    processing_max_pdf_objects: int = Field(default=50_000, gt=0, le=100_000)

    @model_validator(mode="after")
    def validate_processing_lease(self) -> Settings:
        """Reject budgets that guarantee expired work even before persistence overhead."""
        if self.processing_lease_seconds <= (
            self.processing_read_timeout_seconds + self.processing_validation_timeout_seconds + 10
        ):
            raise ValueError("Processing lease must exceed read/validation budgets plus 10 seconds")
        return self

    @field_validator("cors_allowed_origins", "s3_cors_allowed_origins")
    @classmethod
    def validate_cors_origins(cls, origins: tuple[str, ...]) -> tuple[str, ...]:
        """Allow only explicit HTTP(S) origins, never a wildcard or URL with credentials."""
        for origin in origins:
            url = AnyHttpUrl(origin)
            if (
                "*" in origin
                or url.username is not None
                or url.password is not None
                or url.query is not None
                or url.fragment is not None
                or url.path not in {None, "/"}
                or origin.endswith("/")
            ):
                raise ValueError("CORS requires explicit origins without paths or wildcards")
        return origins

    @field_validator("s3_bucket_name")
    @classmethod
    def validate_bucket_name(cls, name: str) -> str:
        """Reject ambiguous DNS names and IP-address-style names before contacting S3."""
        from ipaddress import IPv4Address

        if any(part in name for part in ("..", ".-", "-.")):
            raise ValueError("Invalid bucket name")
        try:
            IPv4Address(name)
        except ValueError:
            return name
        raise ValueError("Bucket name must not be an IP address")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process; tests may clear this cache."""
    return Settings()
