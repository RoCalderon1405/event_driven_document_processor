"""Synthetic Lambda fixture: no document jobs, validation rules, or production transitions."""

import hashlib
import json
import os
import sys
from functools import cache
from typing import Any
from uuid import uuid4

import boto3
from botocore.config import Config

BOOT_ID = uuid4().hex
INVOCATIONS = 0


@cache
def aws_client(service: str) -> Any:
    """Use explicit dummy probe credentials; do not inherit real host/workload credentials."""
    return boto3.client(
        service,
        endpoint_url=os.environ["PROBE_ENDPOINT"],
        region_name="us-east-1",
        aws_access_key_id=os.environ["PROBE_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["PROBE_SECRET_ACCESS_KEY"],
        config=Config(
            signature_version="s3v4" if service == "s3" else "v4",
            s3={"addressing_style": "path"},
            connect_timeout=2,
            read_timeout=3,
            retries={"total_max_attempts": 2},
        ),
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Report runtime reuse, read an exact version, or exercise SQS acknowledgement rules."""
    global INVOCATIONS
    INVOCATIONS += 1
    if event.get("action") == "ping":
        return {
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "boot_id": BOOT_ID,
            "invocations": INVOCATIONS,
            "sdk_version": boto3.__version__,
            "vendored_sdk": boto3.__file__.startswith("/var/task/"),
        }
    table = os.environ["PROBE_TABLE"]
    dynamodb = aws_client("dynamodb")
    if event.get("action") == "read_version":
        response = aws_client("s3").get_object(
            Bucket=event["bucket"], Key=event["key"], VersionId=event["version_id"]
        )
        digest = hashlib.sha256()
        length = 0
        with response["Body"] as stream:
            while chunk := stream.read(65536):
                length += len(chunk)
                if length > 1024 * 1024:
                    raise ValueError("Synthetic probe object exceeded its limit")
                digest.update(chunk)
        result = {"version_id": response["VersionId"], "sha256": digest.hexdigest(), "size": length}
        dynamodb.put_item(
            TableName=table,
            Item={
                "pk": {"S": f"READ#{event['probe_id']}"},
                "version_id": {"S": result["version_id"]},
                "sha256": {"S": result["sha256"]},
                "size": {"N": str(length)},
            },
        )
        return result
    records = event["Records"]
    failures = []
    for record in records:
        payload = json.loads(record["body"])
        response = dynamodb.update_item(
            TableName=table,
            Key={"pk": {"S": f"MESSAGE#{payload['probe_id']}"}},
            UpdateExpression=(
                "SET first_batch_size = if_not_exists(first_batch_size, :batch), "
                "receive_count = :count ADD attempts :one"
            ),
            ExpressionAttributeValues={
                ":batch": {"N": str(len(records))},
                ":count": {"N": record["attributes"]["ApproximateReceiveCount"]},
                ":one": {"N": "1"},
            },
            ReturnValues="ALL_NEW",
        )
        attempt = int(response["Attributes"]["attempts"]["N"])
        mode = payload["mode"]
        if mode == "raise":
            raise RuntimeError("Intentional synthetic invocation failure")
        failed = mode == "always_fail" or (mode == "retry_once" and attempt == 1)
        if failed:
            failures.append({"itemIdentifier": record["messageId"]})
        else:
            dynamodb.update_item(
                TableName=table,
                Key={"pk": {"S": f"MESSAGE#{payload['probe_id']}"}},
                UpdateExpression="SET acknowledged = :yes",
                ExpressionAttributeValues={":yes": {"BOOL": True}},
            )
    return {"batchItemFailures": failures}
