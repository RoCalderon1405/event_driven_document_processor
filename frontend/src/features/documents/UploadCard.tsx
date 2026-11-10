import { useRef, useState } from 'react';

import type { DocumentJob } from './types';
import { useUpload } from './useUpload';
import { ACCEPTED_CONTENT_TYPES, formatFileSize, MAX_FILE_SIZE_BYTES } from './validation';

const ACCEPT_ATTRIBUTE = ACCEPTED_CONTENT_TYPES.join(',');
const MAX_SIZE_LABEL = formatFileSize(MAX_FILE_SIZE_BYTES);

function UploadIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-6"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={1.5}
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
      />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-6"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={2}
      stroke="currentColor"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
    </svg>
  );
}

/**
 * Single-upload card: drag-and-drop or file-picker selection, client-side validation,
 * presigned authorization, direct-to-storage progress, and a delivery confirmation.
 */
export interface UploadCardProps {
  /** Called once per successful storage upload so the app can start status tracking. */
  onUploaded?: (job: DocumentJob) => void;
}

export function UploadCard({ onUploaded }: UploadCardProps) {
  const { state, upload, reset } = useUpload(onUploaded);
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = (files: FileList | null) => {
    const file = files?.[0];
    if (file) upload(file);
  };

  const isActive = state.phase === 'preparing' || state.phase === 'uploading';

  return (
    <section
      aria-labelledby="upload-heading"
      className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8"
    >
      <h2 id="upload-heading" className="text-base font-semibold tracking-tight text-slate-900">
        Upload a document
      </h2>
      <p className="mt-1 text-sm text-slate-500">
        PDF, PNG or JPEG · up to {MAX_SIZE_LABEL} · validated before upload
      </p>

      <div className="mt-5">
        {isActive ? (
          <div
            role="status"
            aria-live="polite"
            className="rounded-xl border border-slate-200 bg-slate-50 p-5"
          >
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="truncate font-medium text-slate-700">{state.fileName}</span>
              <span className="shrink-0 font-medium tabular-nums text-slate-500">
                {state.phase === 'preparing' ? 'Preparing…' : `${state.progress}%`}
              </span>
            </div>
            <div
              role="progressbar"
              aria-label="Upload progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={state.phase === 'preparing' ? 0 : state.progress}
              className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200"
            >
              <div
                className="h-full rounded-full bg-indigo-600 transition-[width] duration-200 ease-out"
                style={{ width: `${state.phase === 'preparing' ? 0 : state.progress}%` }}
              />
            </div>
            <p className="mt-2 text-xs text-slate-500">
              {state.phase === 'preparing'
                ? 'Requesting upload authorization…'
                : `Uploading to private storage · ${formatFileSize(state.fileSizeBytes)}`}
            </p>
          </div>
        ) : state.phase === 'success' ? (
          <div
            role="status"
            className="rounded-xl border border-emerald-200 bg-emerald-50 p-6 text-center"
          >
            <span
              aria-hidden="true"
              className="mx-auto flex size-11 items-center justify-center rounded-full bg-white text-emerald-600 shadow-sm"
            >
              <CheckIcon />
            </span>
            <p className="mt-3 text-sm font-semibold text-emerald-900">Upload complete</p>
            <p className="mt-1 truncate text-sm text-emerald-800">{state.fileName}</p>
            <p className="text-xs text-emerald-700">{formatFileSize(state.fileSizeBytes)}</p>
            {state.jobId && (
              <p className="mt-3 break-all font-mono text-[11px] text-slate-500">
                Job {state.jobId}
              </p>
            )}
            {state.jobId && onUploaded && (
              <p className="mt-1 text-xs text-slate-500">
                Now tracked with live status in Recent Documents below.
              </p>
            )}
            <button
              type="button"
              onClick={() => {
                reset();
                // The dropzone returns on reset; move keyboard focus back to its file input.
                requestAnimationFrame(() => inputRef.current?.focus());
              }}
              className="mt-4 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
            >
              Upload another file
            </button>
          </div>
        ) : (
          <label
            className={[
              'flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition',
              'border-slate-300 bg-slate-50 hover:border-indigo-300 hover:bg-indigo-50/40',
              'has-[:focus-visible]:border-indigo-500 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-indigo-200',
              dragActive ? 'border-indigo-500 bg-indigo-50 ring-2 ring-indigo-200' : '',
            ].join(' ')}
            onDragOver={(event) => {
              event.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={(event) => {
              // Ignore moves that merely crossed into a child element of the dropzone.
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                setDragActive(false);
              }
            }}
            onDrop={(event) => {
              event.preventDefault();
              setDragActive(false);
              handleFiles(event.dataTransfer?.files ?? null);
            }}
          >
            {/* Native file input keeps keyboard and screen-reader behavior free of ARIA scripting. */}
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT_ATTRIBUTE}
              className="sr-only"
              onChange={(event) => {
                handleFiles(event.target.files);
                // Allow re-selecting the same file after a failed attempt.
                event.target.value = '';
              }}
            />
            <span
              aria-hidden="true"
              className="flex size-11 items-center justify-center rounded-full bg-white text-indigo-600 shadow-sm"
            >
              <UploadIcon />
            </span>
            <span className="mt-3 block text-sm font-medium text-slate-700">
              Drop your file here, or <span className="text-indigo-600 underline">browse</span>
            </span>
            <span className="mt-1 block text-xs text-slate-500">
              One file per upload · sent directly to storage
            </span>
          </label>
        )}

        {state.phase === 'error' && state.message && (
          <p
            role="alert"
            className="mt-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            {state.fileName && <span className="font-medium">{state.fileName}: </span>}
            {state.message}
          </p>
        )}
      </div>
    </section>
  );
}
