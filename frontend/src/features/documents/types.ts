/**
 * Response shapes mirrored from the FastAPI schemas in
 * `src/event_driven_document_processor/modules/documents/api/schemas.py`.
 * Keep these in sync with the backend contract; the API forbids unknown request keys.
 */

export type DocumentStatus = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED' | 'DUPLICATE';

export interface DocumentJob {
  job_id: string;
  filename: string;
  content_type: string;
  description: string | null;
  status: DocumentStatus;
  created_at: string;
}

export interface UploadAuthorization {
  method: 'POST';
  url: string;
  fields: Record<string, string>;
  expires_in_seconds: number;
}

export interface CreateUploadResponse {
  job: DocumentJob;
  upload: UploadAuthorization;
}
