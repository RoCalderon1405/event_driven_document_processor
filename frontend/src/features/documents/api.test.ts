import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, createUpload, getJob } from './api';
import type { CreateUploadResponse, DocumentJob } from './types';

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
    fields: { key: 'quarantine/example', policy: 'encoded-policy' },
    expires_in_seconds: 300,
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

const JOB_ID = '6f1d8c2e-0a4b-4c5d-9e8f-0a1b2c3d4e5f';

describe('createUpload', () => {
  it('posts exactly the documented request shape and parses the response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => AUTHORIZATION,
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await createUpload({
      filename: 'report.pdf',
      contentType: 'application/pdf',
      fileSizeBytes: 2048,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/documents/uploads');
    expect(init.method).toBe('POST');
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' });
    // The Pydantic request schema forbids extra keys; never send null description fields.
    expect(JSON.parse(init.body as string)).toEqual({
      filename: 'report.pdf',
      content_type: 'application/pdf',
      file_size_bytes: 2048,
    });
    expect(result.job.job_id).toBe(AUTHORIZATION.job.job_id);
    expect(result.upload.url).toBe(AUTHORIZATION.upload.url);
  });

  it('surfaces fixed backend detail text as an ApiError with its status', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({ detail: 'File exceeds the allowed size' }),
      }),
    );

    await expect(
      createUpload({ filename: 'big.pdf', contentType: 'application/pdf', fileSizeBytes: 1 }),
    ).rejects.toMatchObject({ status: 422, message: 'File exceeds the allowed size' });
  });

  it('never echoes non-string FastAPI validation arrays', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => [{ loc: ['body', 'filename'], msg: 'Field required' }],
      }),
    );

    const error = await createUpload({
      filename: '',
      contentType: 'application/pdf',
      fileSizeBytes: 1,
    }).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe('Upload request failed (HTTP 422)');
  });

  it('propagates network failures for the caller to describe', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    await expect(
      createUpload({ filename: 'a.pdf', contentType: 'application/pdf', fileSizeBytes: 1 }),
    ).rejects.toBeInstanceOf(TypeError);
  });
});

describe('getJob', () => {
  it('fetches the exact job URL uncached and parses the job response', async () => {
    const job: DocumentJob = {
      ...AUTHORIZATION.job,
      status: 'COMPLETED',
      processing: {
        started_at: '2026-11-09T12:00:00Z',
        finished_at: '2026-11-09T12:00:03Z',
        sha256: 'b'.repeat(64),
        size_bytes: 1024,
        failure_code: null,
      },
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => job,
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await getJob(JOB_ID);

    expect(result).toEqual(job);
    expect(result.processing?.sha256).toBe('b'.repeat(64));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/api/v1/documents/${JOB_ID}`);
    expect(init.method).toBe('GET');
    // Polls must not be satisfied by a cached response.
    expect(init.cache).toBe('no-store');
  });

  it('surfaces the fixed 404 detail as an ApiError so polling can stop', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ detail: 'Document job not found' }),
      }),
    );

    await expect(getJob(JOB_ID)).rejects.toMatchObject({
      status: 404,
      message: 'Document job not found',
    });
  });

  it('propagates network failures for the tracker to count', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    await expect(getJob(JOB_ID)).rejects.toBeInstanceOf(TypeError);
  });
});
