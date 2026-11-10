import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { UploadCard } from './UploadCard';
import type { CreateUploadResponse } from './types';
import { UPLOAD_TIMEOUT_MS } from './useUpload';
import { API_TIMEOUT_MS } from './api';

const AUTHORIZATION: CreateUploadResponse = {
  job: {
    job_id: '6f1d8c2e-0a4b-4c5d-9e8f-0a1b2c3d4e5f',
    filename: 'report.pdf',
    content_type: 'application/pdf',
    description: null,
    status: 'PENDING',
    created_at: '2026-11-09T12:00:00Z',
  },
  upload: {
    method: 'POST',
    url: 'http://localhost:4566/document-uploads',
    fields: {
      key: 'quarantine/6f1d8c2e/example',
      policy: 'encoded-policy',
      'x-amz-algorithm': 'AWS4-HMAC-SHA256',
    },
    expires_in_seconds: 300,
  },
};

/**
 * Minimal XMLHttpRequest double: captures the outgoing form and lets tests drive
 * upload progress and terminal statuses exactly like a browser would.
 */
class FakeXMLHttpRequest {
  static instances: FakeXMLHttpRequest[] = [];

  upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  timeout = 0;
  aborted = false;
  status = 0;
  method = '';
  url = '';
  body: FormData | null = null;

  constructor() {
    FakeXMLHttpRequest.instances.push(this);
  }

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  send(body: FormData): void {
    this.body = body;
  }

  abort(): void {
    this.aborted = true;
    this.onabort?.();
  }
}

function pdfFile(): File {
  return new File(['pdf-bytes'], 'report.pdf', { type: 'application/pdf' });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  FakeXMLHttpRequest.instances = [];
  fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 201, json: async () => AUTHORIZATION });
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('XMLHttpRequest', FakeXMLHttpRequest);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('UploadCard', () => {
  it('returns to a retryable picker after authorization times out', async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(() => new Promise(() => {}));
    render(<UploadCard />);
    fireEvent.change(screen.getByLabelText(/drop your file/i), { target: { files: [pdfFile()] } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(API_TIMEOUT_MS);
    });
    expect(screen.getByRole('alert')).toHaveTextContent(/API request timed out/i);
    expect(screen.getByLabelText(/drop your file/i)).toBeInTheDocument();
    expect(FakeXMLHttpRequest.instances).toHaveLength(0);
  });
  it('bounds storage uploads, ignores late success after timeout, and permits a fresh retry', async () => {
    const onUploaded = vi.fn();
    render(<UploadCard onUploaded={onUploaded} />);
    fireEvent.change(screen.getByLabelText(/drop your file/i), { target: { files: [pdfFile()] } });
    await waitFor(() => expect(FakeXMLHttpRequest.instances).toHaveLength(1));
    const xhr = FakeXMLHttpRequest.instances[0];
    expect(xhr.timeout).toBe(UPLOAD_TIMEOUT_MS);
    act(() => {
      xhr.ontimeout?.();
      xhr.status = 204;
      xhr.onload?.();
    });
    expect(screen.getByRole('alert')).toHaveTextContent(/timed out/i);
    expect(onUploaded).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/drop your file/i), { target: { files: [pdfFile()] } });
    await waitFor(() => expect(FakeXMLHttpRequest.instances).toHaveLength(2));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('cancels storage upload and suppresses late progress/success', async () => {
    const onUploaded = vi.fn();
    render(<UploadCard onUploaded={onUploaded} />);
    fireEvent.change(screen.getByLabelText(/drop your file/i), { target: { files: [pdfFile()] } });
    await waitFor(() => expect(FakeXMLHttpRequest.instances).toHaveLength(1));
    const xhr = FakeXMLHttpRequest.instances[0];
    fireEvent.click(screen.getByRole('button', { name: 'Cancel upload' }));
    act(() => {
      xhr.status = 204;
      xhr.onload?.();
      xhr.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 1 } as ProgressEvent);
    });
    expect(xhr.aborted).toBe(true);
    expect(screen.getByLabelText(/drop your file/i)).toBeInTheDocument();
    expect(onUploaded).not.toHaveBeenCalled();
  });

  it('cancels authorization before any storage request starts', async () => {
    let authorize!: (value: unknown) => void;
    fetchMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          authorize = resolve;
        }),
    );
    render(<UploadCard />);
    fireEvent.change(screen.getByLabelText(/drop your file/i), { target: { files: [pdfFile()] } });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel upload' }));
    await act(async () => authorize({ ok: true, json: async () => AUTHORIZATION }));
    expect(FakeXMLHttpRequest.instances).toHaveLength(0);
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it('aborts storage work on unmount', async () => {
    const { unmount } = render(<UploadCard />);
    fireEvent.change(screen.getByLabelText(/drop your file/i), { target: { files: [pdfFile()] } });
    await waitFor(() => expect(FakeXMLHttpRequest.instances).toHaveLength(1));
    unmount();
    expect(FakeXMLHttpRequest.instances[0].aborted).toBe(true);
  });
  it('uploads a valid PDF with progress and confirms delivery', async () => {
    const onUploaded = vi.fn();
    render(<UploadCard onUploaded={onUploaded} />);
    const input = screen.getByLabelText(/drop your file/i);

    fireEvent.change(input, { target: { files: [pdfFile()] } });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      filename: 'report.pdf',
      content_type: 'application/pdf',
      file_size_bytes: 9,
    });

    // Authorization resolved → the storage POST carries signed fields, file part last.
    await waitFor(() => expect(FakeXMLHttpRequest.instances).toHaveLength(1));
    const xhr = FakeXMLHttpRequest.instances[0];
    expect(xhr.method).toBe('POST');
    expect(xhr.url).toBe(AUTHORIZATION.upload.url);
    const form = xhr.body;
    if (!form) throw new Error('storage POST started without a form body');
    const keys = [...form.keys()];
    expect(keys.at(-1)).toBe('file');
    expect(keys).toContain('policy');
    expect(keys).toContain('x-amz-algorithm');
    expect(form.get('file')).toBeInstanceOf(File);
    expect((form.get('file') as File).name).toBe('report.pdf');

    act(() => {
      xhr.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 } as ProgressEvent);
    });
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '50');
    expect(screen.getByText('50%')).toBeInTheDocument();

    act(() => {
      xhr.status = 204;
      xhr.onload?.();
    });
    expect(await screen.findByText('Upload complete')).toBeInTheDocument();
    expect(screen.getByText(new RegExp(AUTHORIZATION.job.job_id))).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /upload another file/i })).toBeInTheDocument();
    // Exactly one handoff per successful storage upload, with the full job for tracking.
    expect(onUploaded).toHaveBeenCalledTimes(1);
    expect(onUploaded).toHaveBeenCalledWith(AUTHORIZATION.job);
    expect(screen.getByText(/Now tracked with live status/i)).toBeInTheDocument();
  });

  it('shows the authorization state before the storage upload starts', async () => {
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})));
    render(<UploadCard />);

    fireEvent.change(screen.getByLabelText(/drop your file/i), {
      target: { files: [pdfFile()] },
    });

    expect(await screen.findByText('Requesting upload authorization…')).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0');
    expect(FakeXMLHttpRequest.instances).toHaveLength(0);
  });

  it('rejects an unsupported file before any network request', async () => {
    render(<UploadCard />);

    fireEvent.change(screen.getByLabelText(/drop your file/i), {
      target: { files: [new File(['x'], 'notes.zip', { type: 'application/zip' })] },
    });

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('notes.zip');
    expect(alert).toHaveTextContent('Unsupported file type');
    expect(fetchMock).not.toHaveBeenCalled();
    expect(FakeXMLHttpRequest.instances).toHaveLength(0);
  });

  it('rejects an oversized file with a clear message', async () => {
    render(<UploadCard />);
    const huge = new File(['x'], 'huge.pdf', { type: 'application/pdf' });
    Object.defineProperty(huge, 'size', { value: 10 * 1024 * 1024 + 1 });

    fireEvent.change(screen.getByLabelText(/drop your file/i), { target: { files: [huge] } });

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('too large');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('accepts a file dropped onto the dropzone', async () => {
    render(<UploadCard />);
    const zone = screen.getByLabelText(/drop your file/i).closest('label');
    if (!zone) throw new Error('dropzone label not found');

    fireEvent.drop(zone, { dataTransfer: { files: [pdfFile()] } });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(FakeXMLHttpRequest.instances).toHaveLength(1);
  });

  it('explains an expired or rejected upload link and offers a retry', async () => {
    render(<UploadCard />);
    fireEvent.change(screen.getByLabelText(/drop your file/i), {
      target: { files: [pdfFile()] },
    });

    await waitFor(() => expect(FakeXMLHttpRequest.instances).toHaveLength(1));
    const xhr = FakeXMLHttpRequest.instances[0];
    act(() => {
      xhr.status = 403;
      xhr.onload?.();
    });

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('expired or was rejected');
    // The dropzone returns so the user can start over with a fresh authorization.
    expect(screen.getByLabelText(/drop your file/i)).toBeInTheDocument();
  });
});
