from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from event_driven_document_processor.bootstrap.dependencies import get_document_service
from event_driven_document_processor.modules.documents.api.schemas import (
    CreateDocumentRequest,
    DocumentJobResponse,
)
from event_driven_document_processor.modules.documents.application.service import DocumentService

router_documents = APIRouter(prefix="/documents", tags=["Documents"])


@router_documents.post(
    "",
    response_model=DocumentJobResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    document: CreateDocumentRequest,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentJobResponse:
    job = service.create_job(
        filename=document.filename,
        content_type=document.content_type,
        description=document.description,
    )
    return DocumentJobResponse.model_validate(job)


@router_documents.get("/{job_id}", response_model=DocumentJobResponse)
def get_document(
    job_id: UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentJobResponse:
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document job not found",
        )
    return DocumentJobResponse.model_validate(job)
