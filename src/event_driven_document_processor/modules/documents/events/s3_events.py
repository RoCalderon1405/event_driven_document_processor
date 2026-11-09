"""Strict decoding of untrusted SQS bodies into saved-reference processing requests."""

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote_plus
from uuid import UUID

from event_driven_document_processor.modules.documents.application.processing_errors import (
    InvalidProcessingEventError,
)
from event_driven_document_processor.modules.documents.domain.models import S3ObjectReference


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys rather than silently hiding an earlier Records value."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class ObjectCreated:
    """Transport-decoded facts; the use case still verifies the persisted reference."""

    job_id: UUID
    reference: S3ObjectReference
    version_id: str


def decode_s3_body(body: str, expected_bucket: str) -> list[ObjectCreated]:
    """Decode once, reject ambiguous keys/versions, and accept only our S3 test event."""
    try:
        if not isinstance(body, str) or len(body.encode("utf-8")) > 256 * 1024:
            raise ValueError
        message = json.loads(body, object_pairs_hook=_unique_object)
        if not isinstance(message, dict):
            raise ValueError
        if message.get("Event") == "s3:TestEvent":
            if (
                message.get("Service") != "Amazon S3"
                or message.get("Bucket") != expected_bucket
                or "Records" in message
            ):
                raise ValueError
            return []
        records = message["Records"]
        if not isinstance(records, list) or not 1 <= len(records) <= 100:
            raise ValueError
        return [_decode_record(record, expected_bucket) for record in records]
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as error:
        raise InvalidProcessingEventError("Invalid S3 notification envelope") from error


def _decode_record(record: dict[str, Any], bucket: str) -> ObjectCreated:
    """Never URL-decode version IDs, normalize paths, or infer a latest version."""
    if (
        record["eventSource"] != "aws:s3"
        or str(record["eventVersion"]).split(".")[0] != "2"
        or record["eventName"]
        not in {
            "ObjectCreated:Post",
            "ObjectCreated:Put",
            "ObjectCreated:Copy",
            "ObjectCreated:CompleteMultipartUpload",
        }
        or record["s3"]["bucket"]["name"] != bucket
    ):
        raise ValueError
    obj = record["s3"]["object"]
    raw_key, version = obj["key"], obj["versionId"]
    if not isinstance(raw_key, str) or re.search(r"%(?![0-9a-fA-F]{2})", raw_key):
        raise ValueError
    key = unquote_plus(raw_key, encoding="utf-8", errors="strict")
    parts = key.split("/", 2)
    if (
        len(parts) != 3
        or parts[0] != "quarantine"
        or not parts[2]
        or len(key.encode("utf-8")) > 1024
        or any(ord(c) < 32 for c in key)
        or not isinstance(version, str)
        or not version.strip()
        or version == "null"
        or len(version) > 1024
    ):
        raise ValueError
    job_id = UUID(parts[1])
    if str(job_id) != parts[1]:
        raise ValueError
    return ObjectCreated(job_id, S3ObjectReference(bucket, key), version)
