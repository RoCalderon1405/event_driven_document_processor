"""Compatibility gates only: synthetic receipts and bytes, never production document jobs."""

import hashlib
import json
import os
from urllib.parse import unquote_plus

import httpx
import pytest

from .conftest import LambdaProbe, wait_for

pytestmark = [
    pytest.mark.lambda_compat,
    pytest.mark.skipif(
        os.getenv("RUN_LAMBDA_COMPATIBILITY") != "1",
        reason="Requires the isolated compose.lambda.yaml stack and explicit Lambda opt-in",
    ),
]


def test_python314_cold_and_warm_invocation(probe: LambdaProbe) -> None:
    name = probe.function()
    cold = probe.invoke(name, {"action": "ping"})
    warm = probe.invoke(name, {"action": "ping"})
    assert cold["python"] == warm["python"] == "3.14"
    assert cold["vendored_sdk"] and warm["vendored_sdk"]
    assert cold["boot_id"] == warm["boot_id"]
    assert (cold["invocations"], warm["invocations"]) == (1, 2)
    print(
        "probe evidence:",
        json.dumps(
            {
                "python": cold["python"],
                "sdk": cold["sdk_version"],
                "cold_counter": 1,
                "warm_counter": 2,
                "same_boot_id": True,
            }
        ),
    )


def test_post_events_select_exact_versions_readable_from_lambda(probe: LambdaProbe) -> None:
    name = probe.function()
    bucket = probe.bucket()
    queue_url, queue_arn = probe.queue()
    probe.sqs.set_queue_attributes(
        QueueUrl=queue_url,
        Attributes={
            "Policy": json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "s3.amazonaws.com"},
                            "Action": "sqs:SendMessage",
                            "Resource": queue_arn,
                            "Condition": {
                                "ArnEquals": {"aws:SourceArn": f"arn:aws:s3:::{bucket}"},
                                "StringEquals": {"aws:SourceAccount": "000000000000"},
                            },
                        }
                    ],
                }
            )
        },
    )
    probe.s3.put_bucket_notification_configuration(
        Bucket=bucket,
        NotificationConfiguration={
            "QueueConfigurations": [
                {
                    "Id": "probe-post-events",
                    "QueueArn": queue_arn,
                    "Events": ["s3:ObjectCreated:*"],
                }
            ],
        },
    )
    key = "probe/version + selection.bin"
    post = probe.s3.generate_presigned_post(
        Bucket=bucket,
        Key=key,
        Fields={"Content-Type": "application/octet-stream"},
        Conditions=[{"Content-Type": "application/octet-stream"}, ["content-length-range", 11, 11]],
        ExpiresIn=300,
    )
    expected = {}
    with httpx.Client(timeout=10, trust_env=False) as http:
        for data in (b"version-one", b"version-two"):
            response = http.post(
                post["url"],
                data=post["fields"],
                files={"file": ("probe.bin", data)},
            )
            assert response.status_code == 204
            version = response.headers["x-amz-version-id"]
            assert version and version != "null"
            expected[version] = data
        assert len(expected) == 2
        object_url = f"{post['url']}/probe/version%20%2B%20selection.bin"
        assert http.get(object_url).status_code == 403
        unsigned = http.post(post["url"], data={"key": key}, files={"file": ("p", b"x")})
        assert unsigned.status_code == 403
        tampered = dict(post["fields"], **{"x-amz-signature": "0" * 64})
        invalid = http.post(post["url"], data=tampered, files={"file": ("p", b"version-one")})
        assert invalid.status_code == 403
    received = {}

    def events_arrived() -> dict | None:
        response = probe.sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=1,
        )
        for message in response.get("Messages", []):
            body = json.loads(message["Body"])
            for record in body.get("Records", []):
                assert record["eventName"] == "ObjectCreated:Post"
                assert record["s3"]["bucket"]["name"] == bucket
                assert unquote_plus(record["s3"]["object"]["key"]) == key
                obj = record["s3"]["object"]
                assert obj.get("sequencer")
                received[obj["versionId"]] = obj["size"]
            probe.sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
        return received if set(received) == set(expected) else None

    wait_for(events_arrived)
    for index, (version, data) in enumerate(expected.items()):
        assert received[version] == len(data)
        result = probe.invoke(
            name,
            {
                "action": "read_version",
                "bucket": bucket,
                "key": key,
                "version_id": version,
                "probe_id": str(index),
            },
        )
        assert result == {
            "version_id": version,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        stored = probe.item(f"READ#{index}")
        assert stored["version_id"]["S"] == version
        assert stored["sha256"]["S"] == result["sha256"]
    print(
        "probe evidence: two authenticated POST versions; exact event versions; "
        "Lambda S3 version reads and DynamoDB writes"
    )


def test_sqs_mapping_partial_failure_retries_only_failed_message(probe: LambdaProbe) -> None:
    name = probe.function()
    probe.invoke(name, {"action": "ping"})
    queue_url, queue_arn = probe.queue()
    mapping = probe.mapping(name, queue_arn)
    probe.sqs.send_message_batch(
        QueueUrl=queue_url,
        Entries=[
            {"Id": "ok", "MessageBody": json.dumps({"probe_id": "ok", "mode": "ok"})},
            {"Id": "retry", "MessageBody": json.dumps({"probe_id": "retry", "mode": "retry_once"})},
        ],
    )
    probe.functions.update_event_source_mapping(UUID=mapping, Enabled=True)

    def completed() -> bool | None:
        return True if probe.item("MESSAGE#retry").get("acknowledged", {}).get("BOOL") else None

    wait_for(completed)
    ok, retry = probe.item("MESSAGE#ok"), probe.item("MESSAGE#retry")
    assert int(ok["first_batch_size"]["N"]) == int(retry["first_batch_size"]["N"]) == 2
    assert int(ok["attempts"]["N"]) == 1
    assert int(retry["attempts"]["N"]) == 2
    assert int(retry["receive_count"]["N"]) == 2
    assert ok["acknowledged"]["BOOL"] is True
    print(
        "probe evidence: batch size=2, successful deliveries=1, failed-then-successful deliveries=2"
    )


@pytest.mark.parametrize("mode", ["always_fail", "raise"])
def test_failed_messages_retry_and_reach_dlq(probe: LambdaProbe, mode: str) -> None:
    name = probe.function()
    probe.invoke(name, {"action": "ping"})
    dlq_url, dlq_arn = probe.queue()
    queue_url, queue_arn = probe.queue(dlq_arn=dlq_arn)
    mapping = probe.mapping(name, queue_arn, batch_size=1)
    body = json.dumps({"probe_id": "poison", "mode": mode})
    original = probe.sqs.send_message(QueueUrl=queue_url, MessageBody=body)
    probe.functions.update_event_source_mapping(UUID=mapping, Enabled=True)

    def dead_lettered() -> dict | None:
        response = probe.sqs.receive_message(QueueUrl=dlq_url, WaitTimeSeconds=1)
        messages = response.get("Messages", [])
        return messages[0] if messages else None

    message = wait_for(dead_lettered, timeout=120)
    assert message["Body"] == body
    assert message["MessageId"] == original["MessageId"]
    item = probe.item("MESSAGE#poison")
    assert int(item["attempts"]["N"]) == 3
    assert int(item["receive_count"]["N"]) == 3
    assert not item.get("acknowledged", {}).get("BOOL")
    print(f"probe evidence: mode={mode}, deliveries=3, original message reached DLQ")
