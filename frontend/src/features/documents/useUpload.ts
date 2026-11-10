import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError, createUpload, RequestTimeoutError } from './api';
import type { DocumentJob } from './types';
import { resolveContentType, validateFile } from './validation';

export type UploadPhase = 'idle' | 'preparing' | 'uploading' | 'success' | 'error';

export const UPLOAD_TIMEOUT_MS = 120_000;

export interface UploadState {
  phase: UploadPhase;
  fileName: string | null;
  fileSizeBytes: number;
  /** Upload completion percentage, 0–100; only meaningful while uploading. */
  progress: number;
  message: string | null;
  jobId: string | null;
}

const IDLE_STATE: UploadState = {
  phase: 'idle',
  fileName: null,
  fileSizeBytes: 0,
  progress: 0,
  message: null,
  jobId: null,
};

export interface UploadController {
  state: UploadState;
  upload: (file: File) => void;
  reset: () => void;
}

/** Turn authorization-stage failures into short, user-facing guidance. */
function describeAuthorizationError(error: unknown): string {
  if (error instanceof RequestTimeoutError) return error.message;
  if (error instanceof ApiError) {
    // Backend validation (422) and outage (503) messages are fixed text, safe to display.
    if (error.status === 422 || error.status === 503) return error.message;
    return `Could not start the upload (HTTP ${error.status}). Please try again.`;
  }
  return 'Could not reach the upload service. Check your connection and try again.';
}

/** Turn storage POST failures into guidance; 403 means the short-lived policy expired. */
function describeStorageStatus(status: number): string {
  if (status === 0) return 'Network error during upload. Check your connection and try again.';
  if (status === 403) return 'The upload link expired or was rejected. Please try again.';
  return `Upload failed (HTTP ${status}). Please try again.`;
}

/**
 * Orchestrate one upload: validate, request presigned authorization, then POST the file
 * directly to storage with real progress events. A single upload runs at a time; the UI
 * hides the dropzone while an attempt is active, so overlapping attempts cannot occur.
 * `onUploaded` receives the created job exactly once, after the storage 2xx.
 */
export function useUpload(onUploaded?: (job: DocumentJob) => void): UploadController {
  const [state, setState] = useState<UploadState>(IDLE_STATE);
  const xhrRef = useRef<XMLHttpRequest | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Read the latest callback from the XHR handler without re-creating upload handlers.
  const onUploadedRef = useRef(onUploaded);
  useEffect(() => {
    onUploadedRef.current = onUploaded;
  });

  // Abort in-flight work on unmount so no state update happens after teardown.
  useEffect(
    () => () => {
      abortRef.current?.abort();
      xhrRef.current?.abort();
    },
    [],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    xhrRef.current?.abort();
    abortRef.current = null;
    xhrRef.current = null;
    setState(IDLE_STATE);
  }, []);

  const upload = useCallback((file: File) => {
    // Stop any previous attempt before starting a new one; its callbacks check this signal.
    abortRef.current?.abort();
    xhrRef.current?.abort();

    const rejection = validateFile(file);
    const contentType = resolveContentType(file);
    if (rejection || !contentType) {
      setState({
        ...IDLE_STATE,
        phase: 'error',
        fileName: file.name,
        fileSizeBytes: file.size,
        message: rejection?.message ?? 'Unsupported file type. Upload a PDF, PNG, or JPEG.',
      });
      return;
    }

    const abort = new AbortController();
    abortRef.current = abort;
    const base: UploadState = {
      phase: 'preparing',
      fileName: file.name,
      fileSizeBytes: file.size,
      progress: 0,
      message: null,
      jobId: null,
    };
    setState(base);

    void (async () => {
      let authorization: Awaited<ReturnType<typeof createUpload>>;
      try {
        authorization = await createUpload(
          { filename: file.name, contentType, fileSizeBytes: file.size },
          abort.signal,
        );
      } catch (error) {
        if (!abort.signal.aborted) {
          setState({ ...base, phase: 'error', message: describeAuthorizationError(error) });
        }
        return;
      }
      if (abort.signal.aborted) return;

      // S3 POST policies require every signed field first; the file part must come last.
      const form = new FormData();
      for (const [name, value] of Object.entries(authorization.upload.fields)) {
        form.append(name, value);
      }
      form.append('file', file, file.name);

      const xhr = new XMLHttpRequest();
      xhrRef.current = xhr;
      xhr.open('POST', authorization.upload.url);
      xhr.timeout = UPLOAD_TIMEOUT_MS;
      let settled = false;
      const fail = (message: string) => {
        if (abort.signal.aborted || settled) return;
        settled = true;
        setState((current) => ({ ...current, phase: 'error', message }));
      };
      xhr.upload.onprogress = (event) => {
        if (!abort.signal.aborted && !settled && event.lengthComputable && event.total > 0) {
          const progress = Math.min(100, Math.round((event.loaded / event.total) * 100));
          setState((current) => ({ ...current, phase: 'uploading', progress }));
        }
      };
      xhr.onload = () => {
        if (abort.signal.aborted || settled) return;
        if (xhr.status >= 200 && xhr.status < 300) {
          // Hand the job to the tracker before the success panel renders so the
          // Recent Documents section already lists it when the user reads it.
          settled = true;
          onUploadedRef.current?.(authorization.job);
          setState((current) => ({
            ...current,
            phase: 'success',
            progress: 100,
            jobId: authorization.job.job_id,
          }));
        } else {
          fail(describeStorageStatus(xhr.status));
        }
      };
      xhr.onerror = () => {
        fail(describeStorageStatus(0));
      };
      xhr.ontimeout = () => fail('Upload timed out. Please try again.');
      xhr.onabort = () => fail('Upload cancelled. Please try again.');
      setState((current) => ({ ...current, phase: 'uploading' }));
      xhr.send(form);
    })();
  }, []);

  return { state, upload, reset };
}
