"""Internal processing facts; deliberately absent from public response schemas."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class FailureCode(StrEnum):
    """Stable, payload-free reasons for permanent document rejection."""

    EMPTY = "EMPTY"
    TOO_LARGE = "TOO_LARGE"
    SIZE_MISMATCH = "SIZE_MISMATCH"
    INVALID_FORMAT = "INVALID_FORMAT"
    FORMAT_MISMATCH = "FORMAT_MISMATCH"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"


@dataclass(frozen=True, slots=True)
class ProcessingMetadata:
    """One selected version and its current fenced attempt, retained after termination."""

    version_id: str
    token: str
    started_at: datetime
    lease_expires_at: datetime
    finished_at: datetime | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    failure_code: FailureCode | None = None

    def __post_init__(self) -> None:
        """Keep corrupt present metadata distinct from legacy records with no metadata."""
        if not self.version_id.strip() or self.version_id == "null" or not self.token.strip():
            raise ValueError("Processing identity must be nonempty and versioned")
        for value in (self.started_at, self.lease_expires_at, self.finished_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("Processing timestamps require timezones")
        if self.lease_expires_at <= self.started_at:
            raise ValueError("Processing lease must end after it starts")
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("Processing cannot finish before starting")
        if self.sha256 is not None and (
            len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256)
        ):
            raise ValueError("Invalid SHA-256 digest")
        if self.size_bytes is not None and (
            type(self.size_bytes) is not int or self.size_bytes <= 0
        ):
            raise ValueError("Processed size must be positive")
