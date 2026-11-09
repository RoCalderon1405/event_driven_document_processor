"""Additive DynamoDB mapping for internal processing facts, not public schemas."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from event_driven_document_processor.modules.documents.domain.processing import (
    FailureCode,
    ProcessingMetadata,
)

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.type_defs import AttributeValueTypeDef


def timestamp(value: datetime) -> str:
    """Normalize fixed-width UTC strings so DynamoDB lexical lease comparisons are valid."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Processing timestamps require a timezone")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def serialize_processing(value: ProcessingMetadata) -> dict[str, AttributeValueTypeDef]:
    """Encode only explicit internal fields; never serialize a whole request or object."""
    result = {
        "version_id": {"S": value.version_id},
        "token": {"S": value.token},
        "started_at": {"S": timestamp(value.started_at)},
        "lease_expires_at": {"S": timestamp(value.lease_expires_at)},
    }
    if value.finished_at is not None:
        result["finished_at"] = {"S": timestamp(value.finished_at)}
    if value.sha256 is not None:
        result["sha256"] = {"S": value.sha256}
    if value.size_bytes is not None:
        result["size_bytes"] = {"N": str(value.size_bytes)}
    if value.failure_code is not None:
        result["failure_code"] = {"S": value.failure_code.value}
    return result


def deserialize_processing(item: dict[str, AttributeValueTypeDef]) -> ProcessingMetadata:
    """Reject corrupt present attributes instead of silently treating them as legacy data."""

    def date(name: str) -> datetime:
        value = datetime.fromisoformat(item[name]["S"])
        if timestamp(value) != item[name]["S"]:
            raise ValueError("Processing timestamp must be normalized UTC")
        return value

    return ProcessingMetadata(
        version_id=item["version_id"]["S"],
        token=item["token"]["S"],
        started_at=date("started_at"),
        lease_expires_at=date("lease_expires_at"),
        finished_at=date("finished_at") if "finished_at" in item else None,
        sha256=item["sha256"]["S"] if "sha256" in item else None,
        size_bytes=int(item["size_bytes"]["N"]) if "size_bytes" in item else None,
        failure_code=FailureCode(item["failure_code"]["S"]) if "failure_code" in item else None,
    )
