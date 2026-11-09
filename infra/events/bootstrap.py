"""Non-destructive, opt-in local provisioning for S3 → SQS → the shared Lambda core."""

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from event_driven_document_processor.bootstrap.event_settings import EventSettings
from event_driven_document_processor.bootstrap.logging import configure_logging
from infra.local.init_dynamodb import ensure_table
from infra.local.init_s3 import ensure_bucket

HANDLER = "event_driven_document_processor.bootstrap.lambda_handler.handler"
NOTIFICATION_ID = "eddp-document-processing"


def _merge_policy(raw: str | None, statement: dict[str, Any]) -> str:
    """Own one Sid only; preserve statements maintained by other local infrastructure."""
    policy = json.loads(raw) if raw else {"Version": "2012-10-17", "Statement": []}
    statements = policy.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    policy["Statement"] = [item for item in statements if item.get("Sid") != statement["Sid"]]
    policy["Statement"].append(statement)
    return json.dumps(policy, sort_keys=True)


def ensure_notifications(s3: Any, bucket: str, queue_arn: str) -> None:
    """Read/merge/write only our notification ID, preserving unrelated notification kinds."""
    current = s3.get_bucket_notification_configuration(Bucket=bucket)
    config = {
        key: current[key]
        for key in (
            "QueueConfigurations",
            "TopicConfigurations",
            "LambdaFunctionConfigurations",
            "EventBridgeConfiguration",
        )
        if key in current
    }
    entry = {
        "Id": NOTIFICATION_ID,
        "QueueArn": queue_arn,
        "Events": ["s3:ObjectCreated:*"],
        "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": "quarantine/"}]}},
    }
    queues = config.get("QueueConfigurations", [])
    updated = [item for item in queues if item.get("Id") != NOTIFICATION_ID] + [entry]
    if queues != updated:
        config["QueueConfigurations"] = updated
        s3.put_bucket_notification_configuration(Bucket=bucket, NotificationConfiguration=config)


def _redrive_allow(raw: str | None, queue_arn: str) -> str:
    """Retain other DLQ sources and explicit allow-all; never override an explicit deny."""
    policy = json.loads(raw) if raw else {"redrivePermission": "byQueue", "sourceQueueArns": []}
    if policy["redrivePermission"] == "allowAll":
        return json.dumps(policy)
    if policy["redrivePermission"] != "byQueue":
        raise ValueError("Existing DLQ denies redrive; refusing to weaken its policy")
    sources = policy["sourceQueueArns"]
    if queue_arn not in sources:
        sources = [*sources, queue_arn]
    if len(sources) > 10:
        raise ValueError("DLQ source policy capacity exceeded")
    return json.dumps(policy | {"sourceQueueArns": sources})


def provision(
    clients: dict[str, Any],
    settings: EventSettings,
    payload: bytes,
    *,
    enabled: bool = True,
    handler: str = HANDLER,
) -> dict[str, str]:
    """Create absent resources and reconcile owned settings without deleting any resource."""
    s3, sqs, ddb, functions, iam = (
        clients[name] for name in ("s3", "sqs", "dynamodb", "lambda", "iam")
    )
    ensure_table(ddb, settings.dynamodb_table_name)
    ensure_bucket(s3, settings.s3_bucket_name, settings.aws_default_region)
    dlq_url = sqs.create_queue(QueueName=settings.processing_dlq_name)["QueueUrl"]
    dlq_attributes = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["All"])[
        "Attributes"
    ]
    dlq_arn = dlq_attributes["QueueArn"]
    queue_url = sqs.create_queue(QueueName=settings.processing_queue_name)["QueueUrl"]
    existing = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["All"])["Attributes"]
    queue_arn = existing["QueueArn"]
    redrive_allow = _redrive_allow(dlq_attributes.get("RedriveAllowPolicy"), queue_arn)
    account_id = queue_arn.split(":")[4]
    try:
        clients["logs"].create_log_group(
            logGroupName=f"/aws/lambda/{settings.processing_function_name}"
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise
    source_statement = {
        "Sid": "EddpS3Notification",
        "Effect": "Allow",
        "Principal": {"Service": "s3.amazonaws.com"},
        "Action": "sqs:SendMessage",
        "Resource": queue_arn,
        "Condition": {
            "ArnEquals": {"aws:SourceArn": f"arn:aws:s3:::{settings.s3_bucket_name}"},
            "StringEquals": {"aws:SourceAccount": account_id},
        },
    }
    sqs.set_queue_attributes(
        QueueUrl=queue_url,
        Attributes={
            "VisibilityTimeout": str(settings.processing_visibility_timeout),
            "ReceiveMessageWaitTimeSeconds": "1",
            # Do not shorten an existing retention period and inadvertently expire old messages.
            "MessageRetentionPeriod": str(
                max(345600, int(existing.get("MessageRetentionPeriod", "0")))
            ),
            "RedrivePolicy": json.dumps(
                {
                    "deadLetterTargetArn": dlq_arn,
                    "maxReceiveCount": settings.processing_max_receive_count,
                }
            ),
            "Policy": _merge_policy(existing.get("Policy"), source_statement),
        },
    )
    sqs.set_queue_attributes(
        QueueUrl=dlq_url,
        Attributes={
            "MessageRetentionPeriod": "1209600",
            "RedriveAllowPolicy": redrive_allow,
        },
    )
    trust = json.dumps(
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
    )
    try:
        role = iam.get_role(RoleName=settings.processing_role_name)["Role"]["Arn"]
    except ClientError as error:
        if error.response["Error"]["Code"] != "NoSuchEntity":
            raise
        role = iam.create_role(
            RoleName=settings.processing_role_name, AssumeRolePolicyDocument=trust
        )["Role"]["Arn"]
    iam.put_role_policy(
        RoleName=settings.processing_role_name,
        PolicyName="eddp-processing",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem"],
                        "Resource": (
                            f"arn:aws:dynamodb:{settings.aws_default_region}:{account_id}"
                            f":table/{settings.dynamodb_table_name}"
                        ),
                        "Condition": {
                            "ForAllValues:StringLike": {"dynamodb:LeadingKeys": ["JOB#*"]}
                        },
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetObjectVersion"],
                        "Resource": f"arn:aws:s3:::{settings.s3_bucket_name}/quarantine/*",
                    },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "sqs:ReceiveMessage",
                            "sqs:DeleteMessage",
                            "sqs:GetQueueAttributes",
                        ],
                        "Resource": queue_arn,
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                        "Resource": (
                            f"arn:aws:logs:{settings.aws_default_region}:{account_id}"
                            f":log-group:/aws/lambda/{settings.processing_function_name}:*"
                        ),
                    },
                ],
            }
        ),
    )
    # The ZIP contains Linux native dependencies and may exceed direct-upload limits.
    # Artifact keys are outside quarantine/, so packaging never generates processing events.
    digest = hashlib.sha256(payload).hexdigest()
    artifact_key = f"lambda-artifacts/{digest}.zip"
    try:
        artifact = s3.head_object(Bucket=settings.s3_bucket_name, Key=artifact_key)
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"404", "NoSuchKey", "NotFound"}:
            raise
        artifact = s3.put_object(Bucket=settings.s3_bucket_name, Key=artifact_key, Body=payload)
    code = {
        "S3Bucket": settings.s3_bucket_name,
        "S3Key": artifact_key,
        "S3ObjectVersion": artifact["VersionId"],
    }
    variables = {
        key.upper(): str(getattr(settings, key))
        for key in type(settings).model_fields
        if key.startswith("processing_")
        or key
        in {
            "dynamodb_table_name",
            "s3_bucket_name",
            "log_level",
            "aws_connect_timeout",
            "aws_read_timeout",
            "aws_max_attempts",
        }
    }
    # No reserved AWS credential environment names are sent to CreateFunction.
    if settings.aws_endpoint_url is not None:
        variables["AWS_ENDPOINT_URL"] = str(settings.aws_endpoint_url)
    if settings.s3_internal_endpoint_url is not None:
        variables["S3_INTERNAL_ENDPOINT_URL"] = str(settings.s3_internal_endpoint_url)
    if os.environ.get("EDDP_LOCAL_EMULATOR") == "1":
        variables["EDDP_LOCAL_EMULATOR"] = "1"
    name = settings.processing_function_name
    desired = {
        "Role": role,
        "Handler": handler,
        "Runtime": "python3.14",
        "Timeout": settings.processing_lambda_timeout,
        "MemorySize": 1024,
        "EphemeralStorage": {"Size": 512},
    }
    try:
        current = functions.get_function_configuration(FunctionName=name)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        functions.create_function(
            FunctionName=name,
            Architectures=["x86_64"],
            Code=code,
            Environment={"Variables": variables},
            **desired,
        )
    else:
        if current.get("Architectures", ["x86_64"]) != ["x86_64"]:
            raise ValueError("Existing function architecture is not the packaged x86_64 target")
        if current["CodeSha256"] != base64.b64encode(hashlib.sha256(payload).digest()).decode():
            functions.update_function_code(FunctionName=name, **code)
            functions.get_waiter("function_updated_v2").wait(FunctionName=name)
        merged = dict(current.get("Environment", {}).get("Variables", {})) | variables
        if any(
            current.get(key) != value for key, value in desired.items()
        ) or merged != current.get("Environment", {}).get("Variables", {}):
            functions.update_function_configuration(
                FunctionName=name, Environment={"Variables": merged}, **desired
            )
            functions.get_waiter("function_updated_v2").wait(FunctionName=name)
    functions.get_waiter("function_active_v2").wait(FunctionName=name)
    matches = []
    for page in functions.get_paginator("list_event_source_mappings").paginate(
        FunctionName=name, EventSourceArn=queue_arn
    ):
        matches.extend(page.get("EventSourceMappings", []))
    mapping_config = {
        "BatchSize": settings.processing_batch_size,
        "FunctionResponseTypes": ["ReportBatchItemFailures"],
        "MaximumBatchingWindowInSeconds": 0,
        "Enabled": enabled,
    }
    if len(matches) > 1:
        raise ValueError(
            "Ambiguous duplicate event-source mappings; refusing destructive reconciliation"
        )
    if matches:
        mapping_id = matches[0]["UUID"]
        functions.update_event_source_mapping(UUID=mapping_id, **mapping_config)
    else:
        mapping_id = functions.create_event_source_mapping(
            FunctionName=name,
            EventSourceArn=queue_arn,
            **mapping_config,
        )["UUID"]
    ensure_notifications(s3, settings.s3_bucket_name, queue_arn)
    return {
        "queue_url": queue_url,
        "queue_arn": queue_arn,
        "dlq_url": dlq_url,
        "dlq_arn": dlq_arn,
        "mapping_id": mapping_id,
        "function_name": name,
    }


def main() -> None:
    """Require an explicit local emulator before provisioning; never silently deploy to AWS."""
    settings = EventSettings()
    configure_logging(settings.log_level)
    endpoint = settings.aws_endpoint_url
    if (
        endpoint is None
        or endpoint.scheme != "http"
        or endpoint.host
        not in {
            "lambda-floci",
            "localhost",
            "127.0.0.1",
        }
        or str(settings.s3_internal_endpoint_url) != str(endpoint)
    ):
        raise ValueError("Event bootstrap requires matching explicit local endpoints")
    clients = {
        name: boto3.client(
            name,
            endpoint_url=str(endpoint),
            region_name=settings.aws_default_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
            config=Config(
                signature_version="s3v4" if name == "s3" else "v4",
                s3={"addressing_style": "path"},
                connect_timeout=settings.aws_connect_timeout,
                # Native ZIP registration can take longer than a small runtime database call.
                read_timeout=90 if name == "lambda" else 10,
                retries={"mode": "standard", "total_max_attempts": settings.aws_max_attempts},
            ),
        )
        for name in ("s3", "sqs", "dynamodb", "lambda", "iam", "logs")
    }
    try:
        provision(clients, settings, Path("artifacts/processing.zip").read_bytes())
        logging.getLogger(__name__).info("Event infrastructure ready")
    finally:
        for client in clients.values():
            client.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Infrastructure diagnostics must not echo SDK payloads or environment values.
        logging.getLogger(__name__).error("Event bootstrap failed error=%s", type(error).__name__)
        raise SystemExit(1) from None
