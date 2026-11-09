"""Real private POST notifications, native Lambda parsing, fencing and SQS redrive."""

import hashlib
import io
import json
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus
from uuid import UUID, uuid4

import httpx
import pytest

from event_driven_document_processor.modules.documents.domain.processing import ProcessingMetadata
from event_driven_document_processor.modules.documents.infrastructure.processing_store import (
    DynamoDBProcessingStore,
)
from infra.events.bootstrap import provision

from .conftest import EventStack, wait_for

pytestmark = [
    pytest.mark.events,
    pytest.mark.skipif(
        os.getenv("RUN_EVENT_TESTS") != "1",
        reason="Requires explicit Lambda overlay event-test runner",
    ),
]


def issue(stack: EventStack, data: bytes, mime: str = "application/pdf") -> tuple[dict, object]:
    """Obtain authorization from the actual API route, with only fixture resource wiring."""
    response = stack.http.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "fixture",
            "content_type": mime,
            "file_size_bytes": len(data),
        },
    )
    assert response.status_code == 201
    result = response.json()
    return result["upload"], stack.repository.get(UUID(result["job"]["job_id"]))


def post(upload: dict, data: bytes) -> str:
    """Use the API-returned signature and URL verbatim over actual multipart HTTP."""
    response = httpx.post(
        upload["url"],
        data=upload["fields"],
        files={"file": ("fixture", data)},
        trust_env=False,
        timeout=15,
    )
    assert response.status_code == 204
    return response.headers["x-amz-version-id"]


def record(job: object, version: str) -> dict:
    return {
        "eventSource": "aws:s3",
        "eventVersion": "2.1",
        "eventName": "ObjectCreated:Post",
        "s3": {
            "bucket": {"name": job.object_reference.bucket},
            "object": {
                "key": quote_plus(job.object_reference.key),
                "versionId": version,
            },
        },
    }


def message(identifier: str, nested: list[dict]) -> dict:
    return {
        "messageId": identifier,
        "eventSource": "aws:sqs",
        "body": json.dumps({"Records": nested}),
    }


def terminal(stack: EventStack, job_id: UUID, timeout: float = 90) -> object:
    def done():
        job = stack.repository.get(job_id)
        return job if job.status in {"COMPLETED", "FAILED"} else None

    return wait_for(done, timeout=timeout)


def mute_notifications(stack: EventStack) -> None:
    """Only this fixture's bucket is changed, to control event order deterministically."""
    stack.clients["s3"].put_bucket_notification_configuration(
        Bucket=stack.settings.s3_bucket_name,
        NotificationConfiguration={},
    )


def test_api_post_to_native_lambda_completes_all_three_formats(event_stack, valid_documents):
    stack = event_stack
    stack.enable(True)  # No warmup: the first real POST exercises cold event-source startup.
    for mime, data in valid_documents.items():
        upload, job = issue(stack, data, mime)
        version = post(upload, data)
        result = terminal(stack, job.job_id)
        assert result.status == "COMPLETED"
        assert result.processing.sha256 == hashlib.sha256(data).hexdigest()
        assert result.processing.version_id == version
        assert result.processing.size_bytes == len(data)
    with zipfile.ZipFile(io.BytesIO(stack.payload)) as archive:
        native = [name for name in archive.namelist() if name.endswith(".so")]
        assert any("pikepdf" in name for name in native)
        assert any("PIL/_imaging" in name for name in native)
        assert not any(name.endswith(".pyd") for name in archive.namelist())
        unpacked = sum(info.file_size for info in archive.infolist())
    print(f"event evidence: native PDF/PNG/JPEG; ZIP={len(stack.payload)} unpacked={unpacked}")


def test_invalid_documents_failed_before_ack(event_stack, valid_documents):
    stack = event_stack
    stack.enable(True)
    for mime, data in valid_documents.items():
        invalid = data[:8] + b"invalid document"
        upload, job = issue(stack, invalid, mime)
        post(upload, invalid)
        result = terminal(stack, job.job_id)
        assert result.status == "FAILED" and result.processing.failure_code == "INVALID_FORMAT"


def test_reversed_duplicate_delayed_and_concurrent_versions(event_stack, valid_documents):
    stack = event_stack
    mute_notifications(stack)
    data = valid_documents["application/pdf"]
    upload, job = issue(stack, data)
    old = post(upload, data)
    newer_data = data.replace(b"100 100", b"101 100", 1)
    assert newer_data != data and len(newer_data) == len(data)
    new = post(upload, newer_data)
    # Deliver newer first: first accepted claim, not object creation order, selects the version.
    assert stack.invoke([message("new", [record(job, new)])]) == {"batchItemFailures": []}
    result = stack.repository.get(job.job_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(lambda v: stack.invoke([message(str(uuid4()), [record(job, v)])]), [old, new])
        )
    assert all(outcome == {"batchItemFailures": []} for outcome in outcomes)
    assert stack.repository.get(job.job_id) == result
    assert result.processing.version_id == new
    assert result.processing.sha256 == hashlib.sha256(newer_data).hexdigest()
    # A real concurrent initial delivery may return an active-claim retry, never corrupt state.
    upload2, job2 = issue(stack, data)
    v2 = post(upload2, data)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(lambda _: stack.invoke([message(str(uuid4()), [record(job2, v2)])]), range(2))
        )
    assert terminal(stack, job2.job_id).processing.sha256 == hashlib.sha256(data).hexdigest()


def test_multi_record_partial_batch_and_test_event(event_stack, valid_documents):
    stack = event_stack
    mute_notifications(stack)
    data = valid_documents["image/png"]
    upload, job = issue(stack, data, "image/png")
    version = post(upload, data)
    missing = replace(
        job,
        job_id=uuid4(),
        object_reference=replace(
            job.object_reference,
            key=f"quarantine/{uuid4()}/missing",
        ),
    )
    mixed = message("outer-mixed", [record(missing, "unknown"), record(job, version)])
    poison = {"messageId": "outer-poison", "eventSource": "aws:sqs", "body": "poison"}
    test = {
        "messageId": "outer-test",
        "eventSource": "aws:sqs",
        "body": json.dumps(
            {
                "Event": "s3:TestEvent",
                "Service": "Amazon S3",
                "Bucket": stack.settings.s3_bucket_name,
            }
        ),
    }
    result = stack.invoke([mixed, poison, test])
    assert result == {
        "batchItemFailures": [
            {"itemIdentifier": "outer-mixed"},
            {"itemIdentifier": "outer-poison"},
        ]
    }
    assert terminal(stack, job.job_id).status == "COMPLETED"
    # Replaying the partially successful message never changes the completed result.
    completed = stack.repository.get(job.job_id)
    stack.invoke([mixed])
    assert stack.repository.get(job.job_id) == completed


def test_active_claim_retries_until_same_version_can_recover(event_stack, valid_documents):
    stack = event_stack
    mute_notifications(stack)
    data = valid_documents["application/pdf"]
    upload, job = issue(stack, data)
    version = post(upload, data)
    now = datetime.now(UTC)
    claim = ProcessingMetadata(version, str(uuid4()), now, now + timedelta(seconds=30))
    store = DynamoDBProcessingStore(stack.clients["dynamodb"], stack.settings.dynamodb_table_name)
    assert store.claim(job, claim, now)
    event = message("active", [record(job, version)])
    assert stack.invoke([event]) == {"batchItemFailures": [{"itemIdentifier": "active"}]}
    assert stack.repository.get(job.job_id).status == "PROCESSING"
    stack.clients["sqs"].send_message(
        QueueUrl=stack.resources["queue_url"], MessageBody=event["body"]
    )
    stack.enable(True)
    completed = terminal(stack, job.job_id, timeout=130)
    assert completed.status == "COMPLETED" and completed.processing.token != claim.token
    print("event evidence: active claim retried and completed after expiry, not acknowledged early")


def test_poison_and_missing_version_reach_dlq_without_failing_valid_job(
    event_stack, valid_documents
):
    stack = event_stack
    mute_notifications(stack)
    upload, job = issue(stack, valid_documents["application/pdf"])
    post(upload, valid_documents["application/pdf"])
    bodies = ["poison payload", json.dumps({"Records": [record(job, "not-an-existing-version")]})]
    sent = {
        stack.clients["sqs"].send_message(QueueUrl=stack.resources["queue_url"], MessageBody=body)[
            "MessageId"
        ]: body
        for body in bodies
    }
    stack.enable(True)
    seen = {}

    def redriven():
        response = stack.clients["sqs"].receive_message(
            QueueUrl=stack.resources["dlq_url"], MaxNumberOfMessages=10, WaitTimeSeconds=1
        )
        for item in response.get("Messages", []):
            seen[item["MessageId"]] = item["Body"]
            stack.clients["sqs"].delete_message(
                QueueUrl=stack.resources["dlq_url"], ReceiptHandle=item["ReceiptHandle"]
            )
        return seen if len(seen) == len(sent) else None

    assert wait_for(redriven, timeout=210) == sent
    assert stack.repository.get(job.job_id).status == "PROCESSING"
    print(
        "event evidence: poison and unavailable selected version reached DLQ; no false FAILED state"
    )


@pytest.mark.parametrize("event_stack", ["crash", "timeout"], indirect=True)
def test_worker_death_after_claim_recovers_on_redelivery(event_stack, valid_documents):
    stack = event_stack
    stack.enable(True)
    data = valid_documents["application/pdf"]
    upload, job = issue(stack, data)
    version = post(upload, data)
    claimed = wait_for(
        lambda: found if (found := stack.repository.get(job.job_id)).processing else None
    )
    original_token = claimed.processing.token
    result = terminal(stack, job.job_id, timeout=150)
    assert result.status == "COMPLETED" and result.processing.version_id == version
    assert result.processing.token != original_token
    print("event evidence: killed/timed-out real worker recovered with a new fencing token")


def test_repeated_bootstrap_preserves_objects_jobs_and_other_notifications(
    event_stack, valid_documents
):
    stack = event_stack
    s3, sqs = stack.clients["s3"], stack.clients["sqs"]
    data = valid_documents["application/pdf"]
    upload, job = issue(stack, data)
    version = post(upload, data)
    config = s3.get_bucket_notification_configuration(Bucket=stack.settings.s3_bucket_name)
    extra = {
        "Id": "unrelated-removal",
        "QueueArn": stack.resources["queue_arn"],
        "Events": ["s3:ObjectRemoved:*"],
    }
    config["QueueConfigurations"].append(extra)
    config.pop("ResponseMetadata", None)
    s3.put_bucket_notification_configuration(
        Bucket=stack.settings.s3_bucket_name, NotificationConfiguration=config
    )
    attrs = sqs.get_queue_attributes(
        QueueUrl=stack.resources["queue_url"], AttributeNames=["Policy"]
    )["Attributes"]
    policy = json.loads(attrs["Policy"])
    other = {
        "Sid": "Unrelated",
        "Effect": "Deny",
        "Principal": "*",
        "Action": "sqs:PurgeQueue",
        "Resource": stack.resources["queue_arn"],
    }
    policy["Statement"].append(other)
    sqs.set_queue_attributes(
        QueueUrl=stack.resources["queue_url"], Attributes={"Policy": json.dumps(policy)}
    )
    for _ in range(2):
        assert (
            provision(stack.clients, stack.settings, stack.payload, enabled=False)
            == stack.resources
        )
    assert stack.repository.get(job.job_id) == job
    response = s3.get_object(
        Bucket=job.object_reference.bucket, Key=job.object_reference.key, VersionId=version
    )
    with response["Body"] as body:
        assert body.read() == data
    assert (
        extra
        in s3.get_bucket_notification_configuration(Bucket=stack.settings.s3_bucket_name)[
            "QueueConfigurations"
        ]
    )
    updated_policy = json.loads(
        sqs.get_queue_attributes(QueueUrl=stack.resources["queue_url"], AttributeNames=["Policy"])[
            "Attributes"
        ]["Policy"]
    )
    assert other in updated_policy["Statement"]
