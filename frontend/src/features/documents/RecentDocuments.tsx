import { failureMessage, formatDuration, formatTimestamp, isTerminalStatus } from './tracking';
import { formatFileSize } from './validation';
import type { TrackedEntry } from './useDocumentTracker';
import type { DocumentStatus } from './types';

interface StatusVisual {
  label: string;
  badge: string;
  dot: string;
}

/** One distinct, palette-consistent badge per backend status. */
const STATUS_VISUALS: Record<DocumentStatus, StatusVisual> = {
  PENDING: { label: 'Pending', badge: 'bg-slate-100 text-slate-600', dot: 'bg-slate-400' },
  PROCESSING: { label: 'Processing', badge: 'bg-amber-100 text-amber-800', dot: 'bg-amber-500' },
  COMPLETED: {
    label: 'Completed',
    badge: 'bg-emerald-100 text-emerald-800',
    dot: 'bg-emerald-500',
  },
  FAILED: { label: 'Failed', badge: 'bg-red-100 text-red-700', dot: 'bg-red-500' },
  DUPLICATE: { label: 'Duplicate', badge: 'bg-violet-100 text-violet-700', dot: 'bg-violet-500' },
};

const LOADING_VISUAL: StatusVisual = {
  label: 'Connecting…',
  badge: 'bg-slate-100 text-slate-500',
  dot: 'bg-slate-300',
};

const MISSING_VISUAL: StatusVisual = {
  label: 'Not found',
  badge: 'bg-slate-100 text-slate-500',
  dot: 'bg-slate-300',
};

const ACTION_BUTTON =
  'rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600';

export interface RecentDocumentsProps {
  entries: TrackedEntry[];
  /** Latest transition message for the polite live region; `null` keeps it silent. */
  announcement: string | null;
  onRetry: (jobId: string) => void;
  onRemove: (jobId: string) => void;
}

/**
 * Recent Documents: every tracked job with its live status, per-entry failure
 * explanations and Retry/Remove controls. Status changes are announced once through a
 * single sr-only live region instead of re-announcing each polling cycle.
 */
export function RecentDocuments({
  entries,
  announcement,
  onRetry,
  onRemove,
}: RecentDocumentsProps) {
  return (
    <section
      aria-labelledby="recent-heading"
      className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="recent-heading" className="text-base font-semibold tracking-tight text-slate-900">
          Recent Documents
        </h2>
        <span className="shrink-0 text-xs text-slate-400">Tracked in this browser</span>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Live status from the local API · refreshed automatically until processing finishes
      </p>

      <p role="status" aria-live="polite" className="sr-only">
        {announcement ?? ''}
      </p>

      {entries.length === 0 ? (
        <p className="mt-4 rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
          No documents tracked yet — successful uploads appear here automatically.
        </p>
      ) : (
        <ul className="mt-4 space-y-3">
          {entries.map(({ tracked, runtime }) => {
            const filename = runtime.lastJob?.filename ?? tracked.filename;
            const visual = runtime.missing
              ? MISSING_VISUAL
              : runtime.lastJob
                ? STATUS_VISUALS[runtime.lastJob.status]
                : LOADING_VISUAL;
            const active =
              !runtime.missing &&
              !runtime.paused &&
              (!runtime.lastJob || !isTerminalStatus(runtime.lastJob.status));
            const canRetry = runtime.paused || runtime.missing;
            // Processing results render only once an attempt has recorded a finish time.
            const results = runtime.lastJob?.processing;
            const finishedMs = results?.finished_at ? Date.parse(results.finished_at) : NaN;
            const startedMs = results ? Date.parse(results.started_at) : NaN;
            const took = finishedMs - startedMs;
            return (
              <li
                key={tracked.job_id}
                className="rounded-xl border border-slate-200 bg-slate-50/60 p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-800">{filename}</p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {formatTimestamp(tracked.added_at)}
                    </p>
                  </div>
                  <span
                    className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${visual.badge}`}
                  >
                    <span
                      aria-hidden="true"
                      className={`size-1.5 rounded-full ${visual.dot} ${active ? 'animate-pulse' : ''}`}
                    />
                    {visual.label}
                  </span>
                </div>

                {runtime.message && <p className="mt-2 text-xs text-red-600">{runtime.message}</p>}

                {results && Number.isFinite(finishedMs) && (
                  <dl className="mt-2 grid gap-x-3 gap-y-1 text-xs text-slate-500 sm:grid-cols-[7.5rem_1fr]">
                    <dt className="text-slate-400">Finished</dt>
                    <dd>
                      {formatTimestamp(finishedMs)}
                      {Number.isFinite(took) && took >= 0 ? ` · took ${formatDuration(took)}` : ''}
                    </dd>
                    {results.size_bytes !== null && (
                      <>
                        <dt className="text-slate-400">Processed size</dt>
                        <dd>{formatFileSize(results.size_bytes)}</dd>
                      </>
                    )}
                    {results.sha256 && (
                      <>
                        <dt className="text-slate-400">SHA-256</dt>
                        <dd className="font-mono break-all">{results.sha256}</dd>
                      </>
                    )}
                    {results.failure_code && (
                      <>
                        <dt className="text-slate-400">Reason</dt>
                        <dd className="text-red-600">{failureMessage(results.failure_code)}</dd>
                      </>
                    )}
                    {runtime.lastJob?.status === 'COMPLETED' && results.sha256 && (
                      <>
                        <dt className="text-slate-400">Validation</dt>
                        <dd>Format validation passed</dd>
                      </>
                    )}
                  </dl>
                )}

                <div className="mt-3 flex flex-wrap gap-2">
                  {canRetry && (
                    <button
                      type="button"
                      className={ACTION_BUTTON}
                      onClick={() => onRetry(tracked.job_id)}
                    >
                      Retry
                    </button>
                  )}
                  <button
                    type="button"
                    className={`${ACTION_BUTTON} text-slate-500`}
                    aria-label={`Remove ${filename} from tracking`}
                    onClick={() => onRemove(tracked.job_id)}
                  >
                    Remove
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
