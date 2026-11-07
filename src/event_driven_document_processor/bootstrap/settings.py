"""Environment-based runtime configuration; credentials stay in boto3's provider chain."""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process; tests may clear this cache."""
    return Settings()
