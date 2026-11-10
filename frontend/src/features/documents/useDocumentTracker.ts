import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { ApiError, getJob } from './api';
import {
  isTerminalStatus,
  MAX_POLL_FAILURES,
  MAX_TRACKED_JOBS,
  POLL_INTERVAL_MS,
  pollDelayMs,
  readTrackedJobs,
  statusLabel,
  writeTrackedJobs,
  type TrackedJob,
} from './tracking';
import type { DocumentJob } from './types';

/** Mutable polling state for one tracked job; `lastJob` is the latest server response. */
export interface JobRuntime {
  lastJob: DocumentJob | null;
  failures: number;
  paused: boolean;
  missing: boolean;
  message: string | null;
}

export interface TrackedEntry {
  tracked: TrackedJob;
  runtime: JobRuntime;
}

export interface DocumentTracker {
  entries: TrackedEntry[];
  track: (job: DocumentJob) => void;
  retry: (jobId: string) => void;
  remove: (jobId: string) => void;
  /** Latest status-transition message for the live region; `null` when quiet. */
  announcement: string | null;
}

const EMPTY_RUNTIME: JobRuntime = {
  lastJob: null,
  failures: 0,
  paused: false,
  missing: false,
  message: null,
};

/**
 * Track uploaded jobs: persist ids in localStorage, poll `GET /documents/{id}` while a
 * job is non-terminal, back off and finally pause on repeated failures, and stop all
 * timers automatically when nothing needs checking. One shared interval polls every
 * active job sequentially, so overlapping requests and duplicate timers cannot occur.
 */
export function useDocumentTracker(): DocumentTracker {
  // State drives rendering; the synchronous callbacks keep mirrored refs authoritative,
  // because React state commits are asynchronous and polls must observe the latest lists.
  const [jobs, setJobs] = useState<TrackedJob[]>(readTrackedJobs);
  const [runtime, setRuntime] = useState<Record<string, JobRuntime>>({});
  const [announcement, setAnnouncement] = useState<string | null>(null);

  const jobsRef = useRef(jobs);
  const runtimeRef = useRef(runtime);
  /** Per-job earliest next attempt time; a scheduling detail that never needs rendering. */
  const nextAttemptRef = useRef(new Map<string, number>());
  const inFlightRef = useRef(new Set<string>());
  // One controller aborts every status request once the hook unmounts. If a StrictMode
  // re-mount reuses the hook, an aborted controller is replaced before the next poll.
  const controllerRef = useRef(new AbortController());
  const tickRef = useRef<() => Promise<void>>(() => Promise.resolve());

  const pollOne = useCallback(async (tracked: TrackedJob): Promise<void> => {
    const id = tracked.job_id;
    if (inFlightRef.current.has(id)) return; // Never stack requests for the same job.
    inFlightRef.current.add(id);

    if (controllerRef.current.signal.aborted) {
      controllerRef.current = new AbortController();
    }
    const signal = controllerRef.current.signal;

    try {
      const job = await getJob(id, signal);
      // The job may have been removed while this request was in flight.
      if (!jobsRef.current.some((entry) => entry.job_id === id)) return;
      const current = runtimeRef.current[id] ?? EMPTY_RUNTIME;
      const updated: JobRuntime = {
        lastJob: job,
        failures: 0,
        paused: false,
        missing: false,
        message: null,
      };
      runtimeRef.current = { ...runtimeRef.current, [id]: updated };
      setRuntime(runtimeRef.current);
      nextAttemptRef.current.delete(id);
      // Announce real transitions only — the initial fetch and repeated identical
      // polls must stay silent so assistive technology is not spammed every cycle.
      if (current.lastJob && current.lastJob.status !== job.status) {
        setAnnouncement(`${job.filename} is now ${statusLabel(job.status)}.`);
      }
    } catch (error) {
      if (signal.aborted) return;
      if (!jobsRef.current.some((entry) => entry.job_id === id)) return;
      const current = runtimeRef.current[id] ?? EMPTY_RUNTIME;
      let updated: JobRuntime;
      if (error instanceof ApiError && error.status === 404) {
        // The backend no longer knows this job (e.g. local data was reset): stop polling
        // but keep the entry visible with an explanation and a manual retry option.
        nextAttemptRef.current.delete(id);
        updated = {
          ...current,
          missing: true,
          message: 'This job no longer exists in backend storage. Remove it or retry later.',
        };
        setAnnouncement(`${tracked.filename} was not found in the backend.`);
      } else {
        const failures = current.failures + 1;
        nextAttemptRef.current.set(id, Date.now() + pollDelayMs(failures));
        if (failures >= MAX_POLL_FAILURES) {
          updated = {
            ...current,
            failures,
            paused: true,
            message: `Status checks paused after ${failures} connection errors. Retry to resume.`,
          };
          setAnnouncement(
            `Status checks paused for ${tracked.filename} after ${failures} connection errors.`,
          );
        } else {
          updated = { ...current, failures };
        }
      }
      runtimeRef.current = { ...runtimeRef.current, [id]: updated };
      setRuntime(runtimeRef.current);
    } finally {
      inFlightRef.current.delete(id);
    }
  }, []);

  const tick = useCallback(async (): Promise<void> => {
    const now = Date.now();
    const targets = jobsRef.current.filter((tracked) => {
      const state = runtimeRef.current[tracked.job_id] ?? EMPTY_RUNTIME;
      if (state.missing || state.paused) return false;
      if (state.lastJob && isTerminalStatus(state.lastJob.status)) return false;
      return now >= (nextAttemptRef.current.get(tracked.job_id) ?? 0);
    });
    // Sequential polls keep failure counting and test timing deterministic.
    for (const tracked of targets) {
      await pollOne(tracked);
    }
  }, [pollOne]);

  // Keep the interval closure pointed at the latest tick without restarting the timer.
  useEffect(() => {
    tickRef.current = tick;
  });

  // Abort in-flight status requests on unmount so no state updates follow teardown.
  useEffect(() => () => controllerRef.current.abort(), []);

  const hasActive = jobs.some((tracked) => {
    const state = runtime[tracked.job_id];
    if (!state) return true; // Persisted but never fetched yet.
    if (state.missing || state.paused) return false;
    return !state.lastJob || !isTerminalStatus(state.lastJob.status);
  });

  // A single timer serves every active job; it starts with an immediate check (page
  // resume or manual retry) and clears itself once no job needs polling anymore.
  useEffect(() => {
    if (!hasActive) return undefined;
    let cancelled = false;
    const run = () => {
      if (!cancelled) void tickRef.current();
    };
    run();
    const timer = window.setInterval(run, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [hasActive]);

  // Persist after every list change (the initializer guarantees hydration first).
  useEffect(() => {
    writeTrackedJobs(jobs);
  }, [jobs]);

  const track = useCallback((job: DocumentJob) => {
    if (jobsRef.current.some((entry) => entry.job_id === job.job_id)) return;
    const entry: TrackedJob = {
      job_id: job.job_id,
      filename: job.filename,
      added_at: Date.now(),
    };
    const nextJobs = [entry, ...jobsRef.current].slice(0, MAX_TRACKED_JOBS);
    jobsRef.current = nextJobs;
    setJobs(nextJobs);

    const kept = new Set(nextJobs.map((tracked) => tracked.job_id));
    const nextRuntime: Record<string, JobRuntime> = {
      ...runtimeRef.current,
      // Seed from the upload response so the entry shows a status before its first poll.
      [job.job_id]: {
        lastJob: job,
        failures: 0,
        paused: false,
        missing: false,
        message: null,
      },
    };
    for (const key of Object.keys(nextRuntime)) {
      if (!kept.has(key)) delete nextRuntime[key]; // Drop runtime for cap-evicted entries.
    }
    runtimeRef.current = nextRuntime;
    setRuntime(nextRuntime);
  }, []);

  const retry = useCallback((jobId: string) => {
    const tracked = jobsRef.current.find((entry) => entry.job_id === jobId);
    if (!tracked) return;
    const current = runtimeRef.current[jobId] ?? EMPTY_RUNTIME;
    const nextRuntime: Record<string, JobRuntime> = {
      ...runtimeRef.current,
      [jobId]: { ...current, failures: 0, paused: false, missing: false, message: null },
    };
    runtimeRef.current = nextRuntime;
    setRuntime(nextRuntime);
    nextAttemptRef.current.delete(jobId);
    setAnnouncement(`Retrying status checks for ${tracked.filename}.`);
  }, []);

  const remove = useCallback((jobId: string) => {
    const removed = jobsRef.current.find((entry) => entry.job_id === jobId);
    if (!removed) return;
    const nextJobs = jobsRef.current.filter((entry) => entry.job_id !== jobId);
    jobsRef.current = nextJobs;
    setJobs(nextJobs);
    const nextRuntime = { ...runtimeRef.current };
    delete nextRuntime[jobId];
    runtimeRef.current = nextRuntime;
    setRuntime(nextRuntime);
    nextAttemptRef.current.delete(jobId);
    setAnnouncement(`Removed ${removed.filename} from Recent Documents.`);
  }, []);

  const entries = useMemo<TrackedEntry[]>(
    () => jobs.map((tracked) => ({ tracked, runtime: runtime[tracked.job_id] ?? EMPTY_RUNTIME })),
    [jobs, runtime],
  );

  return { entries, track, retry, remove, announcement };
}
