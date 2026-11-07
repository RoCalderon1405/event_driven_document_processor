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
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configure logging without making startup depend on AWS network access."""
    configure_logging(get_settings().log_level)
    yield


app = FastAPI(title="EventDriven Document Processor", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)


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
