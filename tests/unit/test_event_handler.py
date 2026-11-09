"""Transport validation, nested acknowledgements and budget checks without SDK calls."""

import json
import logging
import runpy
import zipfile
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import quote_plus
from uuid import uuid4

import pytest
from pydantic import ValidationError

from event_driven_document_processor.bootstrap import lambda_handler
from event_driven_document_processor.bootstrap.event_settings import EventSettings
from event_driven_document_processor.modules.documents.application.processing_errors import (
    InvalidProcessingEventError,
    ProcessingRetryableError,
)
from event_driven_document_processor.modules.documents.events.s3_events import decode_s3_body
from infra.events.bootstrap import _merge_policy, _redrive_allow, ensure_notifications
from infra.events.package import build_archive

BUCKET = "event-uploads"


def s3_record(key: str | None = None, version: str = "version+opaque%2F") -> dict:
    """Use an encoded key while retaining opaque version characters unchanged."""
    return {
        "eventSource": "aws:s3",
        "eventVersion": "2.1",
        "eventName": "ObjectCreated:Post",
        "s3": {
            "bucket": {"name": BUCKET},
            "object": {
                "key": quote_plus(key or f"quarantine/{uuid4()}/private + name"),
                "versionId": version,
            },
        },
    }


def sqs_record(identifier: str, records: list[dict]) -> dict:
    return {
        "messageId": identifier,
        "eventSource": "aws:sqs",
        "body": json.dumps({"Records": records}),
    }


def test_key_decoded_once_and_version_opaque() -> None:
    key = f"quarantine/{uuid4()}/%2F + name"
    request = decode_s3_body(json.dumps({"Records": [s3_record(key)]}), BUCKET)[0]
    assert request.reference.key == key
    assert request.version_id == "version+opaque%2F"


@pytest.mark.parametrize(
    "change",
    [
        {"key": "quarantine%ZZ"},
        {"key": "quarantine%2F%FF"},
        {"versionId": "null"},
        {"versionId": ""},
        {"versionId": None},
        {"key": "outside%2Fkey"},
    ],
)
def test_bad_object_events_rejected(change: dict) -> None:
    record = s3_record()
    record["s3"]["object"].update(change)
    with pytest.raises(InvalidProcessingEventError):
        decode_s3_body(json.dumps({"Records": [record]}), BUCKET)


@pytest.mark.parametrize(
    "body",
    ["not json", "[]", "null", '{"Records":[]}', '{"Records":{}}', '"private"', "x" * 262145],
)
def test_invalid_envelopes_rejected(body: str) -> None:
    with pytest.raises(InvalidProcessingEventError):
        decode_s3_body(body, BUCKET)


def test_duplicate_json_records_are_not_silently_hidden() -> None:
    with pytest.raises(InvalidProcessingEventError):
        decode_s3_body('{"Records":[],"Records":[]}', BUCKET)


def test_expected_s3_test_event_only() -> None:
    body = {"Event": "s3:TestEvent", "Service": "Amazon S3", "Bucket": BUCKET}
    assert decode_s3_body(json.dumps(body), BUCKET) == []
    body["Bucket"] = "wrong"
    with pytest.raises(InvalidProcessingEventError):
        decode_s3_body(json.dumps(body), BUCKET)


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock]:
    monkeypatch.setattr(
        lambda_handler, "initialize_runtime", lambda: EventSettings(s3_bucket_name=BUCKET)
    )
    service = Mock()
    monkeypatch.setattr(lambda_handler, "get_processing_service", lambda: service)
    return service, Mock(get_remaining_time_in_millis=Mock(return_value=900000))


def test_partial_batch_returns_outer_ids_and_handles_every_nested_record(transport: tuple) -> None:
    service, context = transport
    service.process.side_effect = [ProcessingRetryableError("PRIVATE"), "COMPLETED", "FAILED"]
    event = {
        "Records": [
            sqs_record("outer-a", [s3_record(), s3_record()]),
            sqs_record("outer-b", [s3_record()]),
        ]
    }
    assert lambda_handler.handler(event, context) == {
        "batchItemFailures": [{"itemIdentifier": "outer-a"}]
    }
    assert service.process.call_count == 3


def test_poison_does_not_block_other_messages_or_leak_payload(transport: tuple, caplog) -> None:
    service, context = transport
    with caplog.at_level(logging.INFO):
        result = lambda_handler.handler(
            {
                "Records": [
                    {"messageId": "poison", "eventSource": "aws:sqs", "body": "SECRET_POLICY"},
                    sqs_record("good", [s3_record()]),
                ]
            },
            context,
        )
    assert result == {"batchItemFailures": [{"itemIdentifier": "poison"}]}
    assert service.process.call_count == 1
    assert "SECRET_POLICY" not in caplog.text and "private" not in caplog.text


def test_active_claim_and_low_budget_are_not_acknowledged(transport: tuple) -> None:
    service, context = transport
    service.process.side_effect = ProcessingRetryableError()
    event = {"Records": [sqs_record("active", [s3_record()])]}
    assert lambda_handler.handler(event, context)["batchItemFailures"]
    service.process.reset_mock()
    context.get_remaining_time_in_millis.return_value = 1
    assert lambda_handler.handler(event, context)["batchItemFailures"]
    service.process.assert_not_called()


def test_missing_outer_id_fails_entire_batch(transport: tuple) -> None:
    _, context = transport
    with pytest.raises(ValueError):
        lambda_handler.handler({"Records": [{"body": "SECRET"}]}, context)


@pytest.mark.parametrize(
    "change",
    [
        {"processing_lambda_timeout": 180},
        {"processing_visibility_timeout": 899},
        {"processing_max_receive_count": 2},
        {"processing_lambda_timeout": 100},
        {"processing_dlq_name": "document-processing"},
    ],
)
def test_delivery_budget_invariants(change: dict) -> None:
    with pytest.raises(ValidationError):
        EventSettings(**change)


def test_notification_and_queue_policy_merge_preserve_unrelated_entries() -> None:
    original = {
        "QueueConfigurations": [
            {"Id": "other", "QueueArn": "unrelated", "Events": ["s3:ObjectRemoved:*"]}
        ],
        "TopicConfigurations": [
            {"Id": "topic", "TopicArn": "topic", "Events": ["s3:ObjectRemoved:*"]}
        ],
        "EventBridgeConfiguration": {},
    }
    s3 = Mock(get_bucket_notification_configuration=Mock(return_value=original))
    ensure_notifications(s3, BUCKET, "our-queue")
    merged = s3.put_bucket_notification_configuration.call_args.kwargs["NotificationConfiguration"]
    assert merged["TopicConfigurations"] == original["TopicConfigurations"]
    assert merged["QueueConfigurations"][0] == original["QueueConfigurations"][0]
    s3.get_bucket_notification_configuration.return_value = merged
    s3.put_bucket_notification_configuration.reset_mock()
    ensure_notifications(s3, BUCKET, "our-queue")
    s3.put_bucket_notification_configuration.assert_not_called()
    raw = json.dumps({"Statement": [{"Sid": "other", "Effect": "Deny"}]})
    result = json.loads(_merge_policy(raw, {"Sid": "owned", "Effect": "Allow"}))
    assert result["Statement"][0] == {"Sid": "other", "Effect": "Deny"}


def test_package_is_deterministic_and_keeps_native_library_layout(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "pillow.libs").mkdir(parents=True)
    (source / "pillow.libs" / "libjpeg.so").write_bytes(b"ELF fixture")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "cache.pyc").write_bytes(b"skip")
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    build_archive(source, first)
    build_archive(source, second)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["pillow.libs/libjpeg.so"]


def test_dummy_credentials_cannot_target_real_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDDP_LOCAL_EMULATOR", "1")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://s3.amazonaws.com")
    with pytest.raises(ValueError):
        lambda_handler.initialize_runtime()


def test_dlq_sources_are_preserved_without_overriding_deny() -> None:
    raw = json.dumps({"redrivePermission": "byQueue", "sourceQueueArns": ["other"]})
    assert json.loads(_redrive_allow(raw, "ours"))["sourceQueueArns"] == ["other", "ours"]
    with pytest.raises(ValueError):
        _redrive_allow('{"redrivePermission":"denyAll"}', "ours")


def test_fault_fixture_handles_test_notification_before_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = runpy.run_path(str(Path(__file__).resolve().parents[1] / "events/lambda_faults.py"))
    injected = tools["handler"]
    service = Mock()
    service._repository.get.return_value.status = "PENDING"
    delegate = Mock(return_value={"batchItemFailures": []})
    monkeypatch.setitem(
        injected.__globals__, "initialize_runtime", lambda: EventSettings(s3_bucket_name=BUCKET)
    )
    monkeypatch.setitem(injected.__globals__, "get_processing_service", lambda: service)
    monkeypatch.setitem(injected.__globals__, "actual_handler", delegate)
    test = {
        "messageId": "test",
        "eventSource": "aws:sqs",
        "body": json.dumps(
            {
                "Event": "s3:TestEvent",
                "Service": "Amazon S3",
                "Bucket": BUCKET,
            }
        ),
    }
    assert injected({"Records": [test]}, Mock()) == {"batchItemFailures": []}
    service._repository.get.assert_not_called()
    assert injected({"Records": [test, sqs_record("job", [s3_record()])]}, Mock()) == {
        "batchItemFailures": []
    }
    service._repository.get.assert_called_once()
