"""Unique real event-chain resources; no development bucket or normal upload fixture wiring."""

import io
import json
import os
import time
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from event_driven_document_processor.bootstrap.dependencies import (
    get_document_repository,
    get_upload_authorizer,
)
from event_driven_document_processor.bootstrap.event_settings import EventSettings
from event_driven_document_processor.main import app
from event_driven_document_processor.modules.documents.infrastructure.dynamodb_repository import (
    DynamoDBJobRepository,
)
from event_driven_document_processor.modules.documents.infrastructure.s3_upload_authorizer import (
    S3UploadAuthorizer,
)
from infra.events.bootstrap import HANDLER, provision


def wait_for(predicate: Callable, *, timeout: float = 180) -> Any:
    """Poll bounded observable state without swallowing unexpected SDK/assertion failures."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.3)
    raise TimeoutError("Event-chain assertion exceeded its deadline")


@dataclass
class EventStack:
    """Fixture clients plus resource names and real API route access."""

    clients: dict[str, Any]
    settings: EventSettings
    resources: dict[str, str]
    repository: DynamoDBJobRepository
    http: TestClient
    payload: bytes

    def invoke(self, records: list[dict]) -> dict:
        """Invoke the actual handler, without a diagnostic/backdoor operation in production."""
        response = self.clients["lambda"].invoke(
            FunctionName=self.settings.processing_function_name,
            Payload=json.dumps({"Records": records}).encode(),
        )
        with response["Payload"] as stream:
            result = stream.read()
        assert not response.get("FunctionError"), "Business Lambda returned FunctionError"
        return json.loads(result)

    def enable(self, value: bool) -> None:
        """Control this fixture's mapping without touching any other queue consumer."""
        self.clients["lambda"].update_event_source_mapping(
            UUID=self.resources["mapping_id"], Enabled=value
        )


@pytest.fixture
def event_stack(request: pytest.FixtureRequest) -> Iterator[EventStack]:
    endpoint = os.environ["AWS_ENDPOINT_URL"]
    if endpoint != "http://lambda-floci:4566":
        pytest.fail("Event tests require the explicit isolated Lambda emulator")
    prefix = f"event-test-{uuid4().hex[:16]}"
    settings = EventSettings(
        dynamodb_table_name=prefix,
        s3_bucket_name=prefix,
        processing_queue_name=prefix,
        processing_dlq_name=prefix + "-dlq",
        processing_function_name=prefix,
        processing_role_name=prefix,
        processing_lambda_timeout=8,
        processing_visibility_timeout=48,
        processing_max_receive_count=3,
        processing_lease_seconds=30,
        processing_read_timeout_seconds=0.5,
        processing_validation_timeout_seconds=2,
        aws_connect_timeout=0.2,
        aws_read_timeout=0.4,
        aws_max_attempts=1,
    )
    clients = {
        name: boto3.client(
            name,
            endpoint_url=endpoint,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
            config=Config(
                signature_version="s3v4" if name == "s3" else "v4",
                s3={"addressing_style": "path"},
                read_timeout=90 if name == "lambda" else 5,
                retries={"total_max_attempts": 1},
            ),
        )
        for name in ("s3", "sqs", "dynamodb", "lambda", "iam", "logs")
    }
    payload = Path("artifacts/processing.zip").read_bytes()
    fault = getattr(request, "param", None)
    if fault:
        buffer = io.BytesIO(payload)
        with zipfile.ZipFile(buffer, "a", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "test_faults.py", Path(__file__).with_name("lambda_faults.py").read_bytes()
            )
        payload = buffer.getvalue()
    resources = None
    try:
        resources = provision(
            clients,
            settings,
            payload,
            enabled=False,
            handler="test_faults.handler" if fault else HANDLER,
        )
        if fault:
            config = clients["lambda"].get_function_configuration(FunctionName=prefix)
            variables = config["Environment"]["Variables"] | {"TEST_WORKER_FAULT": fault}
            clients["lambda"].update_function_configuration(
                FunctionName=prefix, Environment={"Variables": variables}
            )
        repository = DynamoDBJobRepository(clients["dynamodb"], prefix)
        app.dependency_overrides[get_document_repository] = lambda: repository
        app.dependency_overrides[get_upload_authorizer] = lambda: S3UploadAuthorizer(
            clients["s3"], prefix, 300
        )
        with TestClient(app) as http:
            stack = EventStack(clients, settings, resources, repository, http, payload)
            if request.node.name in {
                "test_reversed_duplicate_delayed_and_concurrent_versions",
                "test_multi_record_partial_batch_and_test_event",
            }:
                # These test exact handler return values, not cold-start budget deferral.
                # A genuine S3 test event warms imports without claiming any document.
                stack.invoke(
                    [
                        {
                            "messageId": "warm",
                            "eventSource": "aws:sqs",
                            "body": json.dumps(
                                {
                                    "Event": "s3:TestEvent",
                                    "Service": "Amazon S3",
                                    "Bucket": prefix,
                                }
                            ),
                        }
                    ]
                )
            yield stack
    finally:
        app.dependency_overrides.clear()
        # No prefix-wide deletion. These exact names were generated in this fixture only.
        if resources:
            functions = clients["lambda"]
            functions.delete_event_source_mapping(UUID=resources["mapping_id"])

            def mapping_deleted() -> bool:
                try:
                    functions.get_event_source_mapping(UUID=resources["mapping_id"])
                except ClientError as error:
                    if error.response["Error"]["Code"] == "ResourceNotFoundException":
                        return True
                    raise
                return False

            wait_for(mapping_deleted, timeout=60)
            functions.delete_function(FunctionName=prefix)
            clients["logs"].delete_log_group(logGroupName=f"/aws/lambda/{prefix}")
            clients["sqs"].delete_queue(QueueUrl=resources["queue_url"])
            clients["sqs"].delete_queue(QueueUrl=resources["dlq_url"])
            clients["s3"].put_bucket_notification_configuration(
                Bucket=prefix, NotificationConfiguration={}
            )
            for page in clients["s3"].get_paginator("list_object_versions").paginate(Bucket=prefix):
                for version in page.get("Versions", []) + page.get("DeleteMarkers", []):
                    clients["s3"].delete_object(
                        Bucket=prefix, Key=version["Key"], VersionId=version["VersionId"]
                    )
            clients["s3"].delete_bucket(Bucket=prefix)
            clients["dynamodb"].delete_table(TableName=prefix)
            clients["iam"].delete_role_policy(RoleName=prefix, PolicyName="eddp-processing")
            clients["iam"].delete_role(RoleName=prefix)
        for client in clients.values():
            client.close()
