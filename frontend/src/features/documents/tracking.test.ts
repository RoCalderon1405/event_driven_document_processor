import { describe, expect, it } from 'vitest';

import {
  formatTimestamp,
  isTerminalStatus,
  MAX_POLL_DELAY_MS,
  MAX_POLL_FAILURES,
  MAX_TRACKED_JOBS,
  parseTrackedJobs,
  pollDelayMs,
  serializeTrackedJobs,
  statusLabel,
} from './tracking';
import type { DocumentStatus } from './types';

const ALL_STATUSES: DocumentStatus[] = [
  'PENDING',
  'PROCESSING',
  'COMPLETED',
  'FAILED',
  'DUPLICATE',
];

describe('status rules', () => {
  it('treats exactly COMPLETED, FAILED and DUPLICATE as terminal', () => {
    // Mirrors ProcessingOutcome.ALREADY_TERMINAL in processing_service.py.
    expect(isTerminalStatus('PENDING')).toBe(false);
    expect(isTerminalStatus('PROCESSING')).toBe(false);
    expect(isTerminalStatus('COMPLETED')).toBe(true);
    expect(isTerminalStatus('FAILED')).toBe(true);
    expect(isTerminalStatus('DUPLICATE')).toBe(true);
  });

  it('has a human label for every backend status', () => {
    expect(ALL_STATUSES.map(statusLabel)).toEqual([
      'Pending',
      'Processing',
      'Completed',
      'Failed',
      'Duplicate',
    ]);
  });
});

describe('pollDelayMs', () => {
  it('backs off from 2s and caps at the delay ceiling', () => {
    expect(pollDelayMs(1)).toBe(2000);
    expect(pollDelayMs(2)).toBe(4000);
    expect(pollDelayMs(3)).toBe(8000);
    expect(pollDelayMs(4)).toBe(MAX_POLL_DELAY_MS);
    expect(pollDelayMs(MAX_POLL_FAILURES)).toBe(MAX_POLL_DELAY_MS);
  });
});

describe('parseTrackedJobs', () => {
  it('returns an empty list for missing, corrupt or non-array storage', () => {
    expect(parseTrackedJobs(null)).toEqual([]);
    expect(parseTrackedJobs('not-json{')).toEqual([]);
    expect(parseTrackedJobs('{"job_id":"x"}')).toEqual([]);
    expect(parseTrackedJobs('[42, null, "x"]')).toEqual([]);
  });

  it('drops malformed and duplicate entries while keeping valid ones', () => {
    const raw = JSON.stringify([
      { job_id: 'a', filename: 'first.pdf', added_at: 1000 },
      { job_id: 'a', filename: 'duplicate-id.pdf', added_at: 2000 },
      { job_id: '', filename: 'empty-id.pdf', added_at: 3000 },
      { job_id: 'b', filename: 7, added_at: 4000 },
      { job_id: 'c', filename: 'no-timestamp.pdf' },
      { job_id: 'd', filename: 'second.pdf', added_at: 5000 },
    ]);
    expect(parseTrackedJobs(raw)).toEqual([
      { job_id: 'd', filename: 'second.pdf', added_at: 5000 },
      { job_id: 'a', filename: 'first.pdf', added_at: 1000 },
    ]);
  });

  it('sorts newest-first and caps at the tracked-job limit', () => {
    const many = Array.from({ length: MAX_TRACKED_JOBS + 5 }, (_, index) => ({
      job_id: `job-${index}`,
      filename: `file-${index}.pdf`,
      added_at: index,
    }));
    const parsed = parseTrackedJobs(JSON.stringify(many));
    expect(parsed).toHaveLength(MAX_TRACKED_JOBS);
    expect(parsed[0].job_id).toBe(`job-${many.length - 1}`); // Newest kept.
    expect(parsed.at(-1)?.job_id).toBe(`job-${5}`); // Oldest evicted.
  });

  it('round-trips through serialization', () => {
    const jobs = [{ job_id: 'a', filename: 'a.pdf', added_at: 123 }];
    expect(parseTrackedJobs(serializeTrackedJobs(jobs))).toEqual(jobs);
  });
});

describe('formatTimestamp', () => {
  it('renders a compact local time for valid values and nothing for invalid ones', () => {
    expect(formatTimestamp(Date.UTC(2026, 10, 9, 12, 5))).toContain(':');
    expect(formatTimestamp(Number.NaN)).toBe('');
  });
});
