"""Application behavior without storage/network clients or duplicated transition logic."""

import hashlib
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from event_driven_document_processor.modules.documents.application.errors import (
    PersistenceUnavailableError,
)
from event_driven_document_processor.modules.documents.application.processing_errors import (
    InvalidDocumentError,
    InvalidProcessingEventError,
    ProcessingRetryableError,
)
from event_driven_document_processor.modules.documents.application.processing_service import (
    ProcessingOutcome,
    ProcessingService,
)
from event_driven_document_processor.modules.documents.domain.enums import DocumentStatus
from event_driven_document_processor.modules.documents.domain.models import (
    DocumentJob,
    S3ObjectReference,
)
from event_driven_document_processor.modules.documents.domain.processing import (
    FailureCode,
    ProcessingMetadata,
)

NOW = datetime(2026, 11, 7, tzinfo=UTC)


class RecordingReader:
    """A stream fixture that detects early cleanup and incremental consumption."""

    def __init__(self, chunks: list[bytes], error: Exception | None = None) -> None:
        self.chunks = chunks
        self.error = error
        self.closed = False
        self.consumed = 0
        self.calls = []

    @contextmanager
    def read(self, reference: S3ObjectReference, version_id: str) -> Iterator[Iterator[bytes]]:
        self.calls.append((reference, version_id))

        def chunks() -> Iterator[bytes]:
            for chunk in self.chunks:
                self.consumed += 1
                yield chunk
            if self.error:
                raise self.error

        try:
            yield chunks()
        finally:
            self.closed = True


@pytest.fixture
def setup_processing() -> tuple:
    job = DocumentJob(
        uuid4(),
        "private-name.pdf",
        "application/pdf",
        "PRIVATE_DESCRIPTION",
        DocumentStatus.PENDING,
        NOW,
        S3ObjectReference("private-bucket", "secret-key"),
    )
    repository = Mock(get=Mock(return_value=job))
    store = Mock(claim=Mock(return_value=True), finish=Mock(return_value=True))
    reader = RecordingReader([b"abc", b"def"])
    validator = Mock()
    service = ProcessingService(
        repository,
        store,
        reader,
        validator,
        max_file_size_bytes=10,
        clock=lambda: NOW,
    )
    return job, repository, store, reader, validator, service


def test_hash_stage_cleanup_and_no_save(setup_processing: tuple, caplog: pytest.LogCaptureFixture):
    job, repository, store, reader, validator, service = setup_processing
    staged = []

    def validate(path: Path, mime: str) -> None:
        assert path.read_bytes() == b"abcdef"
        assert mime == job.content_type
        staged.append(path)

    validator.validate.side_effect = validate
    with caplog.at_level(logging.INFO):
        assert (
            service.process(job.job_id, job.object_reference, "v1") == ProcessingOutcome.COMPLETED
        )
    claim = store.claim.call_args.args[1]
    assert claim.token and claim.version_id == "v1"
    assert claim.lease_expires_at == NOW + timedelta(seconds=180)
    assert store.finish.call_args.kwargs == {
        "sha256": hashlib.sha256(b"abcdef").hexdigest(),
        "size_bytes": 6,
        "failure_code": None,
    }
    assert reader.closed and not staged[0].exists()
    repository.save.assert_not_called()
    assert reader.calls == [(job.object_reference, "v1")]
    assert all(
        value not in caplog.text
        for value in (
            job.filename,
            job.description,
            "secret-key",
            "abcdef",
            "private-bucket",
        )
    )
    assert caplog.records[-1].processing_event == "COMPLETED"


@pytest.mark.parametrize(
    "chunks,declared,code",
    [
        ([], None, FailureCode.EMPTY),
        ([b"a" * 11, b"unread"], None, FailureCode.TOO_LARGE),
        ([b"abc"], 4, FailureCode.SIZE_MISMATCH),
    ],
)
def test_stream_policy_failures(setup_processing: tuple, chunks, declared, code):
    job, repository, store, reader, validator, service = setup_processing
    repository.get.return_value = replace(job, declared_size_bytes=declared)
    reader.chunks = chunks
    assert service.process(job.job_id, job.object_reference, "v1") == ProcessingOutcome.FAILED
    assert store.finish.call_args.kwargs["failure_code"] == code
    assert store.finish.call_args.kwargs["sha256"] is None
    assert reader.closed
    validator.validate.assert_not_called()
    if code == FailureCode.TOO_LARGE:
        assert reader.consumed == 1


def test_permanent_parser_failure_is_sanitized(setup_processing: tuple):
    job, _, store, reader, validator, service = setup_processing
    validator.validate.side_effect = InvalidDocumentError(FailureCode.INVALID_FORMAT)
    assert service.process(job.job_id, job.object_reference, "v1") == ProcessingOutcome.FAILED
    assert store.finish.call_args.kwargs["failure_code"] == FailureCode.INVALID_FORMAT
    assert reader.closed


@pytest.mark.parametrize("stage", ["get", "claim", "read", "validate", "finish"])
def test_infrastructure_failures_preserve_retryability(setup_processing: tuple, stage: str):
    job, repository, store, reader, validator, service = setup_processing
    error = ProcessingRetryableError("unavailable")
    if stage == "get":
        repository.get.side_effect = PersistenceUnavailableError()
    elif stage in {"claim", "finish"}:
        getattr(store, stage).side_effect = PersistenceUnavailableError()
    elif stage == "read":
        reader.error = error
    else:
        validator.validate.side_effect = error
    with pytest.raises((ProcessingRetryableError, PersistenceUnavailableError)):
        service.process(job.job_id, job.object_reference, "v1")
    if stage != "finish":
        store.finish.assert_not_called()
    repository.save.assert_not_called()
    if stage in {"read", "validate", "finish"}:
        assert reader.closed


@pytest.mark.parametrize("stage", ["claim", "finish"])
def test_conflicts_are_retryable_not_success(setup_processing: tuple, stage: str):
    job, _, store, reader, _, service = setup_processing
    getattr(store, stage).return_value = False
    with pytest.raises(ProcessingRetryableError):
        service.process(job.job_id, job.object_reference, "v1")
    if stage == "claim":
        assert not reader.calls
        store.finish.assert_not_called()


@pytest.mark.parametrize("version", ["", "null", " ", None])
def test_missing_versions_rejected_before_access(setup_processing: tuple, version):
    job, repository, store, _, _, service = setup_processing
    with pytest.raises(InvalidProcessingEventError):
        service.process(job.job_id, job.object_reference, version)
    repository.get.assert_not_called()
    store.claim.assert_not_called()


@pytest.mark.parametrize("change", ["bucket", "key", "missing", "metadata_only"])
def test_reference_must_match_saved_job(setup_processing: tuple, change: str):
    job, repository, store, _, _, service = setup_processing
    reference = job.object_reference
    if change == "missing":
        repository.get.return_value = None
    elif change == "metadata_only":
        repository.get.return_value = replace(job, object_reference=None)
    else:
        reference = replace(reference, **{change: "wrong"})
    with pytest.raises(InvalidProcessingEventError):
        service.process(job.job_id, reference, "v1")
    store.claim.assert_not_called()


@pytest.mark.parametrize("status", [DocumentStatus.COMPLETED, DocumentStatus.FAILED])
def test_terminal_and_other_version_events_do_not_read(setup_processing: tuple, status):
    job, repository, store, reader, _, service = setup_processing
    metadata = ProcessingMetadata("v1", "token", NOW, NOW + timedelta(seconds=100))
    repository.get.return_value = replace(job, status=status, processing=metadata)
    assert service.process(job.job_id, job.object_reference, "v1") == "ALREADY_TERMINAL"
    assert service.process(job.job_id, job.object_reference, "v2") == "OTHER_VERSION"
    store.claim.assert_not_called()
    assert not reader.calls


def test_expired_during_validation_cannot_complete(setup_processing: tuple):
    job, _, store, _, _, service = setup_processing
    service._clock = Mock(side_effect=[NOW, NOW + timedelta(seconds=181)])
    store.finish.return_value = False
    with pytest.raises(ProcessingRetryableError):
        service.process(job.job_id, job.object_reference, "v1")
    assert store.finish.call_args.args[2] > store.finish.call_args.args[1].lease_expires_at


def test_read_deadline_closes_stream(setup_processing: tuple, monkeypatch: pytest.MonkeyPatch):
    from event_driven_document_processor.modules.documents.application import processing_service

    job, _, store, reader, _, service = setup_processing
    monkeypatch.setattr(processing_service, "monotonic", Mock(side_effect=[0, 61]))
    with pytest.raises(ProcessingRetryableError):
        service.process(job.job_id, job.object_reference, "v1")
    assert reader.closed
    store.finish.assert_not_called()


def test_staging_failure_is_retryable(setup_processing: tuple, monkeypatch: pytest.MonkeyPatch):
    from event_driven_document_processor.modules.documents.application import processing_service

    job, _, store, _, _, service = setup_processing
    monkeypatch.setattr(processing_service, "TemporaryDirectory", Mock(side_effect=OSError()))
    with pytest.raises(ProcessingRetryableError):
        service.process(job.job_id, job.object_reference, "v1")
    store.finish.assert_not_called()


def test_public_schema_hides_all_internal_facts(setup_processing: tuple):
    from event_driven_document_processor.modules.documents.api.schemas import DocumentJobResponse

    job, _, _, _, _, _ = setup_processing
    result = replace(
        job,
        declared_size_bytes=100,
        processing=ProcessingMetadata(
            "private-version",
            "private-token",
            NOW,
            NOW + timedelta(seconds=10),
        ),
    )
    response = DocumentJobResponse.model_validate(result).model_dump()
    assert set(response) == {
        "job_id",
        "filename",
        "content_type",
        "description",
        "status",
        "created_at",
        "processing",
    }
    # Only the declared safe subset is readable; extra dataclass attributes are ignored.
    assert set(response["processing"]) == {
        "started_at",
        "finished_at",
        "sha256",
        "size_bytes",
        "failure_code",
    }
    assert "private-token" not in repr(response)
    assert "private-version" not in repr(response)
