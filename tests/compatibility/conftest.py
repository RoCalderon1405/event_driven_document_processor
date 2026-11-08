"""Disposable AWS-shaped resources for the opt-in, separate Floci Lambda instance."""

import json
import os
import runpy
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient
    from mypy_boto3_iam import IAMClient
    from mypy_boto3_lambda import LambdaClient
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sqs import SQSClient

TOOLS = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "infra/compatibility/lambda_probe.py")
)
wait_for = TOOLS["wait_for"]


@dataclass
class LambdaProbe:
    """Fixture-only resource factory. Cleanup knows only resources this instance created."""

    endpoint: str
    prefix: str
    table: str
    role_arn: str
    payload: bytes
    stack: ExitStack
    functions: LambdaClient
    sqs: SQSClient
    s3: S3Client
    dynamodb: DynamoDBClient

    def function(self) -> str:
        """Deploy the deterministic ZIP on the pinned official Python 3.14 image."""
        name = f"{self.prefix}-{uuid4().hex[:8]}"
        self.functions.create_function(
            FunctionName=name,
            Runtime="python3.14",
            Architectures=["x86_64"],
            Role=self.role_arn,
            Handler="lambda_handler.handler",
            Code={"ZipFile": self.payload},
            Timeout=5,
            MemorySize=256,
            Environment={
                "Variables": {
                    "PROBE_ENDPOINT": self.endpoint,
                    "PROBE_TABLE": self.table,
                    "PROBE_ACCESS_KEY_ID": "test",
                    "PROBE_SECRET_ACCESS_KEY": "test",
                }
            },
        )
        self.stack.callback(self.functions.delete_function, FunctionName=name)
        self.functions.get_waiter("function_active_v2").wait(
            FunctionName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 60}
        )
        self.functions.put_function_concurrency(FunctionName=name, ReservedConcurrentExecutions=1)
        return name

    def invoke(self, name: str, event: dict[str, Any]) -> dict[str, Any]:
        """Fail without echoing invocation/event contents or credentials into test output."""
        response = self.functions.invoke(FunctionName=name, Payload=json.dumps(event).encode())
        with response["Payload"] as stream:
            payload = stream.read()
        if response.get("FunctionError"):
            raise RuntimeError("Synthetic Lambda invocation returned FunctionError")
        return json.loads(payload)

    def queue(self, *, dlq_arn: str | None = None) -> tuple[str, str]:
        attributes = {"VisibilityTimeout": "5", "ReceiveMessageWaitTimeSeconds": "1"}
        if dlq_arn:
            attributes["RedrivePolicy"] = json.dumps(
                {
                    "deadLetterTargetArn": dlq_arn,
                    "maxReceiveCount": 3,
                }
            )
        url = self.sqs.create_queue(
            QueueName=f"{self.prefix}-{uuid4().hex[:8]}",
            Attributes=attributes,
        )["QueueUrl"]
        self.stack.callback(self.sqs.delete_queue, QueueUrl=url)
        attributes = self.sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])
        arn = attributes["Attributes"]["QueueArn"]
        return url, arn

    def mapping(self, function: str, queue_arn: str, *, batch_size: int = 2) -> str:
        response = self.functions.create_event_source_mapping(
            EventSourceArn=queue_arn,
            FunctionName=function,
            Enabled=False,
            BatchSize=batch_size,
            FunctionResponseTypes=["ReportBatchItemFailures"],
        )
        identifier = response["UUID"]
        self.stack.callback(self._delete_mapping, identifier)
        return identifier

    def _delete_mapping(self, identifier: str) -> None:
        self.functions.delete_event_source_mapping(UUID=identifier)

        def deleted() -> bool | None:
            try:
                self.functions.get_event_source_mapping(UUID=identifier)
            except ClientError as error:
                if error.response["Error"]["Code"] == "ResourceNotFoundException":
                    return True
                raise
            return None

        wait_for(deleted, timeout=60)

    def item(self, key: str) -> dict[str, Any]:
        return self.dynamodb.get_item(
            TableName=self.table,
            Key={"pk": {"S": key}},
            ConsistentRead=True,
        ).get("Item", {})

    def bucket(self) -> str:
        """Versioning/privacy apply only to a new fixture bucket, never development data."""
        name = f"{self.prefix}-{uuid4().hex[:8]}"
        self.s3.create_bucket(Bucket=name)
        self.stack.callback(self._delete_bucket, name)
        self.s3.put_public_access_block(
            Bucket=name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        self.s3.put_bucket_ownership_controls(
            Bucket=name,
            OwnershipControls={"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
        )
        self.s3.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
        return name

    def _delete_bucket(self, name: str) -> None:
        if not name.startswith(self.prefix + "-"):
            raise ValueError("Refusing cleanup outside this probe's resource namespace")
        self.s3.put_bucket_notification_configuration(Bucket=name, NotificationConfiguration={})
        for page in self.s3.get_paginator("list_object_versions").paginate(Bucket=name):
            for item in page.get("Versions", []) + page.get("DeleteMarkers", []):
                self.s3.delete_object(Bucket=name, Key=item["Key"], VersionId=item["VersionId"])
        self.s3.delete_bucket(Bucket=name)


@pytest.fixture(scope="module")
def probe_zip() -> bytes:
    return TOOLS["build_probe_zip"]()


@pytest.fixture
def probe(probe_zip: bytes) -> Iterator[LambdaProbe]:
    endpoint = TOOLS["validate_endpoint"](os.environ["LAMBDA_PROBE_ENDPOINT"])
    prefix = f"lambda-probe-{uuid4().hex[:16]}"
    with ExitStack() as stack:
        clients = {}
        for service in ("lambda", "sqs", "s3", "dynamodb", "iam"):
            clients[service] = boto3.client(
                service,
                endpoint_url=endpoint,
                region_name="us-east-1",
                aws_access_key_id="test",
                aws_secret_access_key="test",
                config=Config(
                    signature_version="s3v4" if service == "s3" else "v4",
                    s3={"addressing_style": "path"},
                    connect_timeout=3,
                    read_timeout=100 if service == "lambda" else 5,
                    retries={"total_max_attempts": 1},
                ),
            )
            stack.callback(clients[service].close)
        iam: IAMClient = clients["iam"]
        role = iam.create_role(
            RoleName=prefix,
            AssumeRolePolicyDocument=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "lambda.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                }
            ),
        )["Role"]["Arn"]
        stack.callback(iam.delete_role, RoleName=prefix)
        dynamodb: DynamoDBClient = clients["dynamodb"]
        dynamodb.create_table(
            TableName=prefix,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        stack.callback(dynamodb.delete_table, TableName=prefix)
        dynamodb.get_waiter("table_exists").wait(
            TableName=prefix,
            WaiterConfig={"Delay": 1, "MaxAttempts": 30},
        )
        yield LambdaProbe(
            endpoint,
            prefix,
            prefix,
            role,
            probe_zip,
            stack,
            clients["lambda"],
            clients["sqs"],
            clients["s3"],
            dynamodb,
        )
