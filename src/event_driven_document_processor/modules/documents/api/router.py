from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from event_driven_document_processor.bootstrap.dependencies import (
    get_document_service,
    get_upload_service,
)
from event_driven_document_processor.modules.documents.api.schemas import (
    CreateDocumentRequest,
    CreateUploadRequest,
    CreateUploadResponse,
    DocumentJobResponse,
    UploadAuthorizationResponse,
)
from event_driven_document_processor.modules.documents.application.service import DocumentService
from event_driven_document_processor.modules.documents.application.upload_service import (
    UploadService,
)

router_documents = APIRouter(prefix="/documents", tags=["Documents"])


@router_documents.post("/uploads", response_model=CreateUploadResponse, status_code=201)
def create_upload(
    document: CreateUploadRequest,
    response: Response,
    service: Annotated[UploadService, Depends(get_upload_service)],
) -> CreateUploadResponse:
    """Create a pending job and short-lived authorization for a private quarantine object."""
    result = service.create_upload_job(
        filename=document.filename,
        content_type=document.content_type,
        description=document.description,
        file_size_bytes=document.file_size_bytes,
    )
    response.headers["Cache-Control"] = "no-store"
    return CreateUploadResponse(
        job=DocumentJobResponse.model_validate(result.job),
        upload=UploadAuthorizationResponse(
            url=result.upload.url,
            fields=result.upload.fields,
            expires_in_seconds=result.upload.expires_in_seconds,
        ),
    )


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
