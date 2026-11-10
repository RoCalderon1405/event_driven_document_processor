import { RecentDocuments } from './features/documents/RecentDocuments';
import { UploadCard } from './features/documents/UploadCard';
import { useDocumentTracker } from './features/documents/useDocumentTracker';

export default function App() {
  const tracker = useDocumentTracker();

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-14 max-w-3xl items-center gap-3 px-4">
          <span
            aria-hidden="true"
            className="flex size-8 items-center justify-center rounded-lg bg-indigo-600 text-white"
          >
            <svg
              className="size-4.5"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.8}
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5A3.375 3.375 0 0 0 10.125 2.25H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
              />
            </svg>
          </span>
          <span className="text-sm font-semibold tracking-tight text-slate-900">
            Document Processor
          </span>
          <span className="ml-auto rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-xs font-medium text-slate-500">
            Local build
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 px-4 pb-16 pt-10 sm:pt-14">
        <p className="text-xs font-semibold uppercase tracking-widest text-indigo-600">
          Event-driven upload
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-900 sm:text-4xl">
          Upload documents, straight to private storage.
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500 sm:text-base">
          Drop a PDF, PNG or JPEG. The browser validates the file, requests a short-lived presigned
          policy from the API, and uploads directly to the quarantine bucket — file bytes never pass
          through the backend. Recent uploads then show live processing status below.
        </p>

        <div className="mt-8">
          <UploadCard onUploaded={tracker.track} />
        </div>

        <div className="mt-6">
          <RecentDocuments
            entries={tracker.entries}
            announcement={tracker.announcement}
            onRetry={tracker.retry}
            onRemove={tracker.remove}
          />
        </div>

        <p className="mt-5 text-xs leading-5 text-slate-400">
          Tracked job IDs stay only in this browser&apos;s local storage. Remove an entry to stop
          tracking it.
        </p>
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-3xl px-4 py-5 text-xs text-slate-400">
          Event-Driven Document Processor · local development interface
        </div>
      </footer>
    </div>
  );
}
