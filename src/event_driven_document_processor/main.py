from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from event_driven_document_processor.bootstrap.logging import configure_logging
from event_driven_document_processor.bootstrap.routes import api_router
from event_driven_document_processor.bootstrap.settings import get_settings
from event_driven_document_processor.modules.documents.application.errors import (
    PersistenceDataError,
    PersistenceUnavailableError,
    UploadAuthorizationUnavailableError,
    UploadValidationError,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configure logging without making startup depend on AWS network access."""
    configure_logging(get_settings().log_level)
    yield


app = FastAPI(title="EventDriven Document Processor", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)


@app.exception_handler(UploadValidationError)
async def upload_validation_error(request: Request, error: UploadValidationError) -> JSONResponse:
    """Application validation messages are fixed text, never echoed SDK/request payloads."""
    return JSONResponse(
        status_code=422, content={"detail": str(error)}, headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(UploadAuthorizationUnavailableError)
async def upload_unavailable(
    request: Request, error: UploadAuthorizationUnavailableError,
) -> JSONResponse:
    """Hide all credentials, endpoints, and signing material on authorization failures."""
    return JSONResponse(
        status_code=503, content={"detail": "Upload authorization temporarily unavailable"},
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(PersistenceUnavailableError)
async def persistence_unavailable(
    request: Request,
    error: PersistenceUnavailableError,
) -> JSONResponse:
    """Do not expose infrastructure details or confuse outages with missing records."""
    return JSONResponse(status_code=503, content={"detail": "Job storage temporarily unavailable"})


@app.exception_handler(PersistenceDataError)
async def persistence_data_error(request: Request, error: PersistenceDataError) -> JSONResponse:
    """Keep corrupt stored data out of HTTP responses."""
    return JSONResponse(status_code=500, content={"detail": "Unable to retrieve document job"})


@app.get("/health", tags=["Health"])
def health() -> dict[str, str]:
    return {"status": "healthy", "service": "document-processor"}
