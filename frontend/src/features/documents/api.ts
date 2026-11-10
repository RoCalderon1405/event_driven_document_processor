import type { CreateUploadResponse, DocumentJob } from './types';

/**
 * Base URL for API calls. The default empty value routes requests through the Vite dev
 * proxy (`/api` → `http://127.0.0.1:8000`), keeping API traffic same-origin in development.
 * Set `VITE_API_BASE_URL` to call the API directly instead (requires backend CORS).
 */
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

export const API_TIMEOUT_MS = 15_000;

export class RequestTimeoutError extends Error {
  constructor() {
    super('The API request timed out. Please try again.');
    this.name = 'RequestTimeoutError';
  }
}

/** Bound headers AND body reads; caller cancellation never becomes a timeout. */
async function withDeadline<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  caller?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  let cancel = () => {};
  let timer: ReturnType<typeof setTimeout> | undefined;
  const interrupted = new Promise<never>((_, reject) => {
    cancel = () => {
      const reason = caller?.reason ?? new DOMException('Request cancelled', 'AbortError');
      controller.abort(reason);
      reject(reason);
    };
    if (caller?.aborted) cancel();
    else caller?.addEventListener('abort', cancel, { once: true });
    timer = setTimeout(() => {
      const error = new RequestTimeoutError();
      controller.abort(error);
      reject(error);
    }, API_TIMEOUT_MS);
  });
  try {
    return await Promise.race([
      interrupted,
      // Do not dispatch a request if it was cancelled before this call.
      controller.signal.aborted ? interrupted : operation(controller.signal),
    ]);
  } finally {
    clearTimeout(timer);
    caller?.removeEventListener('abort', cancel);
  }
}

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
  return withDeadline(async (requestSignal) => {
    const response = await fetch(`${API_BASE}/api/v1/documents/uploads`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // The request schema forbids unknown keys, so send exactly its documented shape.
      body: JSON.stringify({
        filename: request.filename,
        content_type: request.contentType,
        file_size_bytes: request.fileSizeBytes,
      }),
      signal: requestSignal,
    });
    if (!response.ok) {
      throw new ApiError(response.status, await readDetail(response));
    }
    return (await response.json()) as CreateUploadResponse;
  }, signal);
}

/**
 * Read the current job state for status tracking. `cache: 'no-store'` keeps polled
 * responses fresh even if an intermediary would otherwise reuse a cached GET.
 * A 404 surfaces as `ApiError(404, ...)` so the tracker can stop polling that job.
 */
export async function getJob(jobId: string, signal?: AbortSignal): Promise<DocumentJob> {
  return withDeadline(async (requestSignal) => {
    const response = await fetch(`${API_BASE}/api/v1/documents/${jobId}`, {
      method: 'GET',
      cache: 'no-store',
      signal: requestSignal,
    });
    if (!response.ok) {
      throw new ApiError(response.status, await readDetail(response));
    }
    return (await response.json()) as DocumentJob;
  }, signal);
}
