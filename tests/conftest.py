import io

import pikepdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from event_driven_document_processor.bootstrap.dependencies import get_document_repository
from event_driven_document_processor.main import app
from event_driven_document_processor.modules.documents.infrastructure.in_memory_repository import (
    InMemoryJobRepository,
)


@pytest.fixture
def client():
    repository = InMemoryJobRepository()
    app.dependency_overrides[get_document_repository] = lambda: repository
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def repository(client):
    """The in-memory repository wired behind the overridden API dependency."""
    return app.dependency_overrides[get_document_repository]()


@pytest.fixture(scope="session")
def valid_documents() -> dict[str, bytes]:
    """Generate genuine minimal documents with maintained encoders, not header-only fakes."""
    documents = {}
    with pikepdf.new() as pdf:
        pdf.add_blank_page(page_size=(100, 100))
        buffer = io.BytesIO()
        pdf.save(buffer)
        documents["application/pdf"] = buffer.getvalue()
    for mime, fmt in (("image/png", "PNG"), ("image/jpeg", "JPEG")):
        buffer = io.BytesIO()
        with Image.new("RGB", (8, 8), color="blue") as image:
            image.save(buffer, format=fmt)
        documents[mime] = buffer.getvalue()
    return documents
