/**
 * Response shapes mirrored from the FastAPI schemas in
 * `src/event_driven_document_processor/modules/documents/api/schemas.py`.
 * Keep these in sync with the backend contract; the API forbids unknown request keys.
 */

export type DocumentStatus = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED' | 'DUPLICATE';

/** Stable, payload-free rejection reasons; mirrors `FailureCode` in `domain/processing.py`. */
export type FailureCode =
  'EMPTY' | 'TOO_LARGE' | 'SIZE_MISMATCH' | 'INVALID_FORMAT' | 'FORMAT_MISMATCH' | 'RESOURCE_LIMIT';

/**
 * Safe public subset of the backend `ProcessingMetadata`: the lease, token and object
 * version stay internal. Null until an attempt claims the job; `finished_at`,
 * `sha256`, `size_bytes` and `failure_code` fill in once it finishes.
 */
export interface ProcessingResult {
  started_at: string;
  finished_at: string | null;
  sha256: string | null;
  size_bytes: number | null;
  failure_code: FailureCode | null;
}

export interface DocumentJob {
  job_id: string;
  filename: string;
  content_type: string;
  description: string | null;
  status: DocumentStatus;
  created_at: string;
  processing?: ProcessingResult | null;
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
