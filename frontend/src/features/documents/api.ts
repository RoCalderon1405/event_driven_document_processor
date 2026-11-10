import type { CreateUploadResponse, DocumentJob } from './types';

/**
 * Base URL for API calls. The default empty value routes requests through the Vite dev
 * proxy (`/api` → `http://127.0.0.1:8000`), keeping API traffic same-origin in development.
 * Set `VITE_API_BASE_URL` to call the API directly instead (requires backend CORS).
 */
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

/** HTTP failure with a message that is always safe to display in the UI. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export interface UploadRequest {
  filename: string;
  contentType: string;
  fileSizeBytes: number;
}

/** Extract the backend's fixed `detail` text; never echo arbitrary error bodies. */
async function readDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === 'string') return detail;
      // FastAPI validation errors use an array detail; its field text is not shown verbatim.
    }
  } catch {
    // Non-JSON error body: fall through to the generic message below.
  }
  return `Upload request failed (HTTP ${response.status})`;
}

/**
 * Create a pending job and obtain short-lived presigned POST authorization.
 * The file itself is uploaded directly to storage, never to this endpoint.
 */
export async function createUpload(
  request: UploadRequest,
  signal?: AbortSignal,
): Promise<CreateUploadResponse> {
  const response = await fetch(`${API_BASE}/api/v1/documents/uploads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // The request schema forbids unknown keys, so send exactly its documented shape.
    body: JSON.stringify({
      filename: request.filename,
      content_type: request.contentType,
      file_size_bytes: request.fileSizeBytes,
    }),
    signal,
  });
  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response));
  }
  return (await response.json()) as CreateUploadResponse;
}

/**
 * Read the current job state for status tracking. `cache: 'no-store'` keeps polled
 * responses fresh even if an intermediary would otherwise reuse a cached GET.
 * A 404 surfaces as `ApiError(404, ...)` so the tracker can stop polling that job.
 */
export async function getJob(jobId: string, signal?: AbortSignal): Promise<DocumentJob> {
  const response = await fetch(`${API_BASE}/api/v1/documents/${jobId}`, {
    method: 'GET',
    cache: 'no-store',
    signal,
  });
  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response));
  }
  return (await response.json()) as DocumentJob;
}
