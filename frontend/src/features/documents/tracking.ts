/**
 * Pure tracking rules: status semantics, polling/backoff policy and localStorage
 * persistence. Kept free of React so every rule is directly unit-testable.
 */

import type { DocumentStatus, FailureCode } from './types';

/** Versioned key so a future persisted-schema change cannot silently break older data. */
export const STORAGE_KEY = 'eddp.tracked-jobs.v1';

/** Upper bound of tracked jobs; the oldest entries are dropped when it is exceeded. */
export const MAX_TRACKED_JOBS = 20;

/** Base cadence for jobs that still need a status check. */
export const POLL_INTERVAL_MS = 2_000;

/** Consecutive failures before automatic polling pauses and waits for a manual retry. */
export const MAX_POLL_FAILURES = 5;

/** Backoff ceiling so a recovered connection resumes within a bounded delay. */
export const MAX_POLL_DELAY_MS = 15_000;

/**
 * Terminal outcomes — mirrors `ProcessingOutcome.ALREADY_TERMINAL` in
 * `processing_service.py`; polling must stop for these statuses.
 */
const TERMINAL_STATUSES: readonly DocumentStatus[] = ['COMPLETED', 'FAILED', 'DUPLICATE'];

const STATUS_LABELS: Record<DocumentStatus, string> = {
  PENDING: 'Pending',
  PROCESSING: 'Processing',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
  DUPLICATE: 'Duplicate',
};

/** The subset of a job persisted in this browser: enough to render before the first fetch. */
export interface TrackedJob {
  job_id: string;
  filename: string;
  /** Epoch milliseconds when this browser started tracking; drives ordering and display. */
  added_at: number;
}

/** Whether the backend will not advance the job any further. */
export function isTerminalStatus(status: DocumentStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export function statusLabel(status: DocumentStatus): string {
  return STATUS_LABELS[status];
}

/**
 * User-facing explanations for every payload-free backend failure code. Unknown future
 * codes fall back to the raw stable code instead of rendering nothing.
 */
const FAILURE_MESSAGES: Partial<Record<FailureCode, string>> = {
  EMPTY: 'The stored file was empty, so there was nothing to validate.',
  TOO_LARGE: 'The stored file exceeded the processing size limit.',
  SIZE_MISMATCH: 'The stored size did not match the size declared at upload.',
  INVALID_FORMAT: 'The content could not be parsed as a valid document.',
  FORMAT_MISMATCH: 'The content does not match the file type declared at upload.',
  RESOURCE_LIMIT: 'Validation resource limits (pages, objects or pixels) were exceeded.',
};

export function failureMessage(code: FailureCode): string {
  return FAILURE_MESSAGES[code] ?? code;
}

/**
 * Delay before the next attempt after `failures` consecutive errors:
 * 2s → 4s → 8s → 15s (capped). Attempt 5 pauses tracking instead.
 */
export function pollDelayMs(failures: number): number {
  const delay = POLL_INTERVAL_MS * 2 ** Math.max(0, failures - 1);
  return Math.min(delay, MAX_POLL_DELAY_MS);
}

/**
 * Parse persisted jobs defensively: corrupt JSON, wrong shapes and duplicate ids are
 * dropped rather than breaking the page, and the result is sorted newest-first and capped.
 */
export function parseTrackedJobs(raw: string | null): TrackedJob[] {
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return []; // Corrupt storage: the next save replaces it with a clean list.
  }
  if (!Array.isArray(parsed)) return [];

  const seen = new Set<string>();
  const jobs: TrackedJob[] = [];
  for (const item of parsed) {
    if (typeof item !== 'object' || item === null) continue;
    const candidate = item as Partial<TrackedJob>;
    if (typeof candidate.job_id !== 'string' || candidate.job_id.length === 0) continue;
    if (typeof candidate.filename !== 'string') continue;
    if (typeof candidate.added_at !== 'number' || !Number.isFinite(candidate.added_at)) continue;
    if (seen.has(candidate.job_id)) continue;
    seen.add(candidate.job_id);
    jobs.push({
      job_id: candidate.job_id,
      filename: candidate.filename,
      added_at: candidate.added_at,
    });
  }
  return jobs.sort((a, b) => b.added_at - a.added_at).slice(0, MAX_TRACKED_JOBS);
}

export function serializeTrackedJobs(jobs: TrackedJob[]): string {
  return JSON.stringify(jobs);
}

/** Read persisted jobs; unavailable storage (private mode) degrades to session-only tracking. */
export function readTrackedJobs(): TrackedJob[] {
  try {
    return parseTrackedJobs(globalThis.localStorage.getItem(STORAGE_KEY));
  } catch {
    return [];
  }
}

export function writeTrackedJobs(jobs: TrackedJob[]): void {
  try {
    globalThis.localStorage.setItem(STORAGE_KEY, serializeTrackedJobs(jobs));
  } catch {
    // Storage failures are non-fatal: tracking simply does not survive a refresh.
  }
}

/** Compact local timestamp for list rows; invalid values render nothing. */
export function formatTimestamp(epochMs: number): string {
  const date = new Date(epochMs);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** Compact processing duration (e.g. "2.4 s"); invalid values render nothing. */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '';
  const seconds = ms / 1000;
  return seconds < 10 ? `${seconds.toFixed(1)} s` : `${Math.round(seconds)} s`;
}
