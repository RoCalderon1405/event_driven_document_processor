from fastapi import APIRouter

from event_driven_document_processor.modules.documents.api.router import (
    router_documents,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(router_documents)