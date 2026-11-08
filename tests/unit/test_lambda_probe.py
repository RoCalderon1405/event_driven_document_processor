"""Check probe safety/packaging without Docker, network access, or resource creation."""

import io
import runpy
import zipfile
from pathlib import Path

import pytest

TOOLS = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "infra/compatibility/lambda_probe.py")
)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://lambda.us-east-1.amazonaws.com",
        "http://floci:4566",
        "http://test:test@localhost:4566",
        "http://localhost:4566/other",
    ],
)
def test_probe_refuses_nonisolated_endpoints(endpoint: str) -> None:
    with pytest.raises(ValueError):
        TOOLS["validate_endpoint"](endpoint)


def test_probe_accepts_explicit_local_endpoint() -> None:
    assert TOOLS["validate_endpoint"]("http://lambda-floci:4566/") == "http://lambda-floci:4566"


def test_probe_zip_is_deterministic_and_separate_from_application() -> None:
    first = TOOLS["build_probe_zip"]()
    assert first == TOOLS["build_probe_zip"]()
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        names = archive.namelist()
        assert "lambda_handler.py" in names
        assert "boto3/__init__.py" in names
        assert "botocore/__init__.py" in names
        unexpected = [name for name in names if "event_driven_document_processor" in name]
        assert not unexpected, unexpected[:5]
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
