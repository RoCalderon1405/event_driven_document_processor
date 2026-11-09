"""Thin SQS Lambda adapter; all claims, hashing and validation stay in ProcessingService."""

import logging
import os
from typing import Any
from urllib.parse import urlsplit

from event_driven_document_processor.bootstrap.event_settings import EventSettings
from event_driven_document_processor.bootstrap.logging import configure_logging
from event_driven_document_processor.bootstrap.processing import get_processing_service
from event_driven_document_processor.modules.documents.events.s3_events import decode_s3_body

logger = logging.getLogger(__name__)


def initialize_runtime() -> EventSettings:
    """Local Floci uses explicit dummy credentials; real deployments use the role chain."""
    settings = EventSettings()
    configure_logging(settings.log_level)
    if os.environ.get("EDDP_LOCAL_EMULATOR") == "1":
        endpoints = [settings.aws_endpoint_url, settings.s3_internal_endpoint_url]
        if any(
            endpoint is None
            or urlsplit(str(endpoint)).hostname
            not in {
                "lambda-floci",
                "localhost",
                "127.0.0.1",
            }
            or endpoint.scheme != "http"
            for endpoint in endpoints
        ):
            raise ValueError("Dummy Lambda credentials require explicit local HTTP endpoints")
        os.environ["AWS_ACCESS_KEY_ID"] = "test"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
        os.environ.pop("AWS_SESSION_TOKEN", None)
    return settings


def handler(event: dict[str, Any], context: Any) -> dict[str, list[dict[str, str]]]:
    """Acknowledge a message only if every nested event is safely handled or ignored."""
    settings = initialize_runtime()
    records = event.get("Records")
    if not isinstance(records, list) or not 1 <= len(records) <= 10:
        raise ValueError("Expected a nonempty SQS batch")
    # Without an outer message ID no partial acknowledgement is safe: fail the whole batch.
    if any(
        not isinstance(record, dict)
        or not isinstance(record.get("messageId"), str)
        or not record["messageId"]
        for record in records
    ):
        raise ValueError("SQS batch contains a record without a message ID")
    failures = []
    for record in records:
        failed = False
        try:
            if record.get("eventSource") != "aws:sqs":
                raise ValueError("Expected an SQS record")
            requests = decode_s3_body(record["body"], settings.s3_bucket_name)
            for request in requests:
                try:
                    if (
                        context.get_remaining_time_in_millis()
                        < settings.record_budget_seconds * 1000
                    ):
                        raise TimeoutError("Insufficient remaining processing budget")
                    get_processing_service().process(
                        request.job_id,
                        request.reference,
                        request.version_id,
                    )
                except Exception:
                    # Even unexpected adapter failures are retried, never logged with payloads.
                    # Successful nested records can be replayed safely on the next delivery.
                    failed = True
        except Exception:
            failed = True
        if failed:
            failures.append({"itemIdentifier": record["messageId"]})
        logger.info(
            "sqs_message outcome=%s",
            "retry" if failed else "handled",
            extra={"delivery_outcome": "retry" if failed else "handled"},
        )
    return {"batchItemFailures": failures}
