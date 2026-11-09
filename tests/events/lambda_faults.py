"""Test-only process death/timeout injection after the real core has committed its claim."""

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from event_driven_document_processor.bootstrap.lambda_handler import handler as actual_handler
from event_driven_document_processor.bootstrap.lambda_handler import initialize_runtime
from event_driven_document_processor.bootstrap.processing import get_processing_service
from event_driven_document_processor.modules.documents.domain.models import S3ObjectReference
from event_driven_document_processor.modules.documents.events.s3_events import decode_s3_body


def handler(event: dict, context: Any) -> dict:
    """Fault one initial attempt; restarted/timed-out invocations must recover the same lease."""
    settings = initialize_runtime()
    processor = get_processing_service()
    requests = [
        request
        for message in event["Records"]
        for request in decode_s3_body(message["body"], settings.s3_bucket_name)
    ]
    if not requests:
        return actual_handler(event, context)
    job = processor._repository.get(requests[0].job_id)
    original = processor._reader
    if job.status == "PENDING":

        class FaultReader:
            """Die or block only after the real service's claim boundary."""

            @contextmanager
            def read(self, reference: S3ObjectReference, version: str) -> Iterator[Iterator[bytes]]:
                """Inject a process-level fault, not a simulated conditional store."""
                # Entered only after ProcessingService's actual DynamoDB claim succeeds.
                if os.environ["TEST_WORKER_FAULT"] == "crash":
                    os._exit(1)
                time.sleep(60)
                with original.read(reference, version) as chunks:
                    yield chunks

        processor._reader = FaultReader()
    else:
        # A timed-out runtime may be reused by the emulator; do not keep the injected reader.
        from event_driven_document_processor.bootstrap.aws import create_s3_client
        from event_driven_document_processor.modules.documents.infrastructure import (
            s3_object_reader,
        )

        processor._reader = s3_object_reader.S3ObjectReader(create_s3_client(settings))
    result = actual_handler(event, context)
    print(json.dumps({"test_fault_result": "returned"}))
    return result
