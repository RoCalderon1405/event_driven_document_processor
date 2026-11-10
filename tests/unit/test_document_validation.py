"""Real decoders reject corruption and limits, including header-only impostors."""

import io
import struct
import subprocess
import zlib
from pathlib import Path
from unittest.mock import Mock

import pikepdf
import pytest
from PIL import Image

from event_driven_document_processor.modules.documents.application.processing_errors import (
    InvalidDocumentError,
    ProcessingRetryableError,
)
from event_driven_document_processor.modules.documents.domain.processing import FailureCode
from event_driven_document_processor.modules.documents.infrastructure.document_validator import (
    IsolatedDocumentValidator,
)


@pytest.mark.parametrize("mime", ["application/pdf", "image/png", "image/jpeg"])
def test_genuine_formats(tmp_path: Path, valid_documents: dict, mime: str):
    path = tmp_path / "input"
    path.write_bytes(valid_documents[mime])
    IsolatedDocumentValidator().validate(path, mime)


@pytest.mark.parametrize("mime", ["application/pdf", "image/png", "image/jpeg"])
@pytest.mark.parametrize("damage", ["truncate", "header_only", "mismatch", "corrupt"])
def test_bad_formats(tmp_path: Path, valid_documents: dict, mime: str, damage: str):
    data = valid_documents[mime]
    if damage == "truncate":
        data = data[:-15]
    elif damage == "header_only":
        data = data[:8] + b"not a document"
    elif damage == "corrupt":
        data = data[:8] + b"x" * (len(data) - 24) + data[-16:]
    else:
        mime = "image/png" if mime == "application/pdf" else "application/pdf"
    path = tmp_path / "input"
    path.write_bytes(data)
    with pytest.raises(InvalidDocumentError) as caught:
        IsolatedDocumentValidator().validate(path, mime)
    assert caught.value.code == (
        FailureCode.FORMAT_MISMATCH if damage == "mismatch" else FailureCode.INVALID_FORMAT
    )


def test_image_and_pdf_limits(tmp_path: Path, valid_documents: dict):
    path = tmp_path / "input"
    path.write_bytes(valid_documents["image/png"])
    for validator in (
        IsolatedDocumentValidator(max_pixels=10),
        IsolatedDocumentValidator(max_dimension=4),
    ):
        with pytest.raises(InvalidDocumentError) as caught:
            validator.validate(path, "image/png")
        assert caught.value.code == FailureCode.RESOURCE_LIMIT
    with pikepdf.new() as pdf:
        pdf.add_blank_page()
        pdf.add_blank_page()
        pdf.save(path)
    with pytest.raises(InvalidDocumentError) as caught:
        IsolatedDocumentValidator(max_pdf_pages=1).validate(path, "application/pdf")
    assert caught.value.code == FailureCode.RESOURCE_LIMIT
    with pytest.raises(InvalidDocumentError):
        IsolatedDocumentValidator(max_pdf_objects=1).validate(path, "application/pdf")


def test_encrypted_pdf_is_rejected(tmp_path: Path):
    path = tmp_path / "encrypted"
    with pikepdf.new() as pdf:
        pdf.add_blank_page()
        pdf.save(path, encryption=pikepdf.Encryption(owner="owner", user="password"))
    with pytest.raises(InvalidDocumentError):
        IsolatedDocumentValidator().validate(path, "application/pdf")


def test_animated_png_is_rejected(tmp_path: Path):
    path = tmp_path / "animated"
    with Image.new("RGB", (2, 2), "blue") as first, Image.new("RGB", (2, 2), "red") as second:
        first.save(path, format="PNG", save_all=True, append_images=[second])
    with pytest.raises(InvalidDocumentError):
        IsolatedDocumentValidator().validate(path, "image/png")


def _background_disposal_apng(disposal: int) -> bytes:
    """Tiny GHSA-5xm2-6676-qcp9 case: 100x100 canvas, 1x1 first frame.

    Even an unpatched decoder can allocate only 40 KB for this canvas. Never use
    the advisory's multi-gigabyte dimensions in the test suite.
    """

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 100, 100, 8, 6, 0, 0, 0))
        + chunk(b"acTL", struct.pack(">II", 2, 0))
        + chunk(b"fcTL", struct.pack(">IIIIIHHBB", 0, 1, 1, 0, 0, 1, 10, disposal, 0))
        + chunk(b"IDAT", zlib.compress(bytes(5)))
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize("disposal", [1, 2], ids=["background", "previous"])
def test_apng_bomb_check_precedes_canvas_allocation(
    monkeypatch: pytest.MonkeyPatch, disposal: int
) -> None:
    """Both disposal modes must reject oversized headers before native allocation."""
    fill = Mock(side_effect=AssertionError("APNG allocated before its pixel-limit check"))
    monkeypatch.setattr(Image.core, "fill", fill)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(Image.DecompressionBombError):
        Image.open(io.BytesIO(_background_disposal_apng(disposal)))
    fill.assert_not_called()


@pytest.mark.parametrize("disposal", [1, 2], ids=["background", "previous"])
def test_apng_bomb_is_resource_limit_in_isolated_validator(tmp_path: Path, disposal: int) -> None:
    """The real child process retains the API's fixed RESOURCE_LIMIT classification."""
    path = tmp_path / "bounded-apng.png"
    path.write_bytes(_background_disposal_apng(disposal))
    with pytest.raises(InvalidDocumentError) as caught:
        IsolatedDocumentValidator(max_pixels=10).validate(path, "image/png")
    assert caught.value.code == FailureCode.RESOURCE_LIMIT


def test_missing_staged_file_remains_retryable(tmp_path: Path) -> None:
    with pytest.raises(ProcessingRetryableError):
        IsolatedDocumentValidator().validate(tmp_path / "missing", "application/pdf")


@pytest.mark.parametrize("mode", ["timeout", "crash", "start_failure"])
def test_worker_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str):
    run = Mock(return_value=subprocess.CompletedProcess([], 1))
    if mode == "timeout":
        run.side_effect = subprocess.TimeoutExpired("validator", 1)
    elif mode == "start_failure":
        run.side_effect = OSError("internal")
    monkeypatch.setattr(subprocess, "run", run)
    expected = InvalidDocumentError if mode == "timeout" else ProcessingRetryableError
    with pytest.raises(expected):
        IsolatedDocumentValidator().validate(tmp_path / "input", "application/pdf")
