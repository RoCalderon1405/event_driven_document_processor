import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  MAX_POLL_FAILURES,
  MAX_TRACKED_JOBS,
  POLL_INTERVAL_MS,
  serializeTrackedJobs,
  STORAGE_KEY,
} from './tracking';
import type { DocumentJob } from './types';
import { useDocumentTracker } from './useDocumentTracker';

const JOB_ID = '6f1d8c2e-0a4b-4c5d-9e8f-0a1b2c3d4e5f';

function job(overrides: Partial<DocumentJob> = {}): DocumentJob {
  return {
    job_id: JOB_ID,
    filename: 'report.pdf',
    content_type: 'application/pdf',
    description: null,
    status: 'PENDING',
    created_at: '2026-11-09T12:00:00Z',
    ...overrides,
  };
}

function jsonResponse(payload: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => payload };
}

/** Drain promise chains started by effects without moving the fake clock. */
async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(0);
  });
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  localStorage.clear();
  // Fake the clock and timers together so backoff math follows virtual time.
  vi.useFakeTimers({
    toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'],
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('useDocumentTracker', () => {
  it('resumes persisted jobs and stops polling at a terminal status', async () => {
    localStorage.setItem(
      STORAGE_KEY,
      serializeTrackedJobs([{ job_id: JOB_ID, filename: 'report.pdf', added_at: 1000 }]),
    );
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(job({ status: 'PENDING' })))
      .mockResolvedValueOnce(jsonResponse(job({ status: 'COMPLETED' })));
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useDocumentTracker());
    await flush();

    expect(result.current.entries).toHaveLength(1);
    expect(result.current.entries[0].runtime.lastJob?.status).toBe('PENDING');
    // The first observation sets the baseline without announcing anything.
    expect(result.current.announcement).toBeNull();

    await advance(POLL_INTERVAL_MS);
    expect(result.current.entries[0].runtime.lastJob?.status).toBe('COMPLETED');
    expect(result.current.announcement).toBe('report.pdf is now Completed.');

    const callsAtTerminal = fetchMock.mock.calls.length;
    await advance(POLL_INTERVAL_MS * 10);
    // Terminal state: the shared interval cleared itself, so no further requests happen.
    expect(fetchMock.mock.calls.length).toBe(callsAtTerminal);
  });

  it('tracks a fresh upload, persists it, and announces only real transitions', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(job({ status: 'PENDING' })))
      .mockResolvedValueOnce(jsonResponse(job({ status: 'PROCESSING' })))
      .mockResolvedValueOnce(jsonResponse(job({ status: 'PROCESSING' })));
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useDocumentTracker());
    act(() => {
      result.current.track(job());
    });
    await flush();

    expect(result.current.entries).toHaveLength(1);
    expect(result.current.entries[0].runtime.lastJob?.status).toBe('PENDING');
    expect(localStorage.getItem(STORAGE_KEY)).toContain(JOB_ID);
    expect(result.current.announcement).toBeNull();

    await advance(POLL_INTERVAL_MS);
    expect(result.current.announcement).toBe('report.pdf is now Processing.');

    await advance(POLL_INTERVAL_MS);
    // An identical status must not re-announce on every poll cycle.
    expect(result.current.entries[0].runtime.lastJob?.status).toBe('PROCESSING');
    expect(result.current.announcement).toBe('report.pdf is now Processing.');
  });

  it('backs off on failures, pauses after the limit, and resumes on retry', async () => {
    const fetchMock = vi.fn();
    for (let attempt = 0; attempt < MAX_POLL_FAILURES; attempt += 1) {
      fetchMock.mockRejectedValueOnce(new TypeError('network down'));
    }
    fetchMock.mockResolvedValue(jsonResponse(job({ status: 'PENDING' })));
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useDocumentTracker());
    act(() => {
      result.current.track(job());
    });
    await flush(); // Failure 1 at t0 → next attempt t0 + 2s.
    await advance(POLL_INTERVAL_MS); // Failure 2 at t0+2s → next attempt t0+6s.
    await advance(POLL_INTERVAL_MS * 4); // Failure 3 at t0+6s.
    await advance(POLL_INTERVAL_MS * 4); // Failure 4 at t0+14s.
    await advance(POLL_INTERVAL_MS * 8); // Failure 5 at t0+30s → paused.

    expect(fetchMock).toHaveBeenCalledTimes(MAX_POLL_FAILURES);
    const entry = result.current.entries[0];
    expect(entry.runtime.failures).toBe(MAX_POLL_FAILURES);
    expect(entry.runtime.paused).toBe(true);
    expect(entry.runtime.message).toContain('paused after 5 connection errors');
    expect(result.current.announcement).toContain('paused for report.pdf');

    await advance(POLL_INTERVAL_MS * 30);
    expect(fetchMock).toHaveBeenCalledTimes(MAX_POLL_FAILURES); // Paused jobs never poll.

    act(() => {
      result.current.retry(JOB_ID);
    });
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(MAX_POLL_FAILURES + 1);
    expect(result.current.entries[0].runtime.paused).toBe(false);
    expect(result.current.entries[0].runtime.failures).toBe(0);
    expect(result.current.entries[0].runtime.lastJob?.status).toBe('PENDING');
  });

  it('stops polling a job the backend no longer knows and removes it on demand', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: 'Document job not found' }, 404));
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useDocumentTracker());
    act(() => {
      result.current.track(job());
    });
    await flush();

    expect(result.current.entries[0].runtime.missing).toBe(true);
    expect(result.current.entries[0].runtime.message).toContain('no longer exists');
    expect(result.current.announcement).toContain('was not found');

    await advance(POLL_INTERVAL_MS * 10);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.remove(JOB_ID);
    });
    expect(result.current.entries).toHaveLength(0);
    expect(localStorage.getItem(STORAGE_KEY)).toBe('[]');
    expect(result.current.announcement).toContain('Removed report.pdf');
  });

  it('clears timers and stops fetching after unmount', async () => {
    // PROCESSING is non-terminal, so polling would continue if cleanup failed.
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(job({ status: 'PROCESSING' })));
    vi.stubGlobal('fetch', fetchMock);

    const { result, unmount } = renderHook(() => useDocumentTracker());
    act(() => {
      result.current.track(job());
    });
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    unmount();
    await advance(POLL_INTERVAL_MS * 10);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('caps the tracked list by evicting the oldest entry', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(job())));

    const { result } = renderHook(() => useDocumentTracker());
    act(() => {
      for (let index = 0; index <= MAX_TRACKED_JOBS; index += 1) {
        result.current.track(job({ job_id: `job-${index}`, filename: `file-${index}.pdf` }));
      }
    });
    await flush();

    expect(result.current.entries).toHaveLength(MAX_TRACKED_JOBS);
    expect(result.current.entries[0].tracked.job_id).toBe(`job-${MAX_TRACKED_JOBS}`);
    expect(result.current.entries.at(-1)?.tracked.job_id).toBe('job-1');
  });
});
