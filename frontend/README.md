# Frontend — Event-Driven Document Processor

A minimal, responsive React interface for uploading PDF/PNG/JPEG documents through the existing
FastAPI presigned-POST flow, with live processing-status tracking. Built with **React 19 +
TypeScript + Vite + Tailwind CSS v4**.

Phase 1 added direct-to-storage uploads; Phase 2 added the Recent Documents section, which polls the
API for real job status until a terminal state; Phase 3 shows the processing results those polls
return (digest, size, timing and failure reasons). Phase 4 adds a dedicated frontend CI job.

## Requirements

- **Node.js 24** (any actively supported ≥ 20.19 works; verified with 24.19 / npm 11)
- The backend stack running locally: `docker compose up --build -d --wait api`

## Commands

GitHub Actions runs these same locked-install quality gates on PRs, master pushes and manual
dispatch with Node.js 24: `npm ci`, lint, formatting, tests and production build. See
[CI security and reproduction](../infra/ci/README.md). Hosted execution still requires publishing
the workflow; local checks do not prove a GitHub-hosted run.

```sh
cd frontend
npm ci                 # reproducible install from package-lock.json
npm run dev            # dev server on http://localhost:5173
npm test               # Vitest + Testing Library (jsdom), no network
npm run test:coverage  # Same suite with V8 line/branch coverage and LCOV
npm run lint           # ESLint (flat config, typescript-eslint + react-hooks)
npm run format:check   # Prettier verification
npm run build          # tsc -b type-check + production bundle
npm run preview        # serve the production bundle locally
```

## How an upload flows

1. The browser validates the file locally (type, size ≤ 10 MiB, file-name length) — no network.
2. `POST /api/v1/documents/uploads` sends only `{filename, content_type, file_size_bytes}` and
   receives `{job, upload: {url, fields, expires_in_seconds}}`.
3. An `XMLHttpRequest` POSTs the signed `fields` plus the file (file part **last**) directly to
   storage; `upload.onprogress` drives the real progress bar.
4. HTTP 2xx from storage shows the confirmation panel with the job ID and hands the job to the
   tracker, which lists it under Recent Documents. 403 is reported as an expired/rejected link,
   since presigned policies are short-lived and never renewed (ADR 0002).

File bytes never pass through FastAPI.

## Status tracking (Phase 2)

- A single shared interval polls `GET /api/v1/documents/{job_id}` every **2 s** while any tracked
  job is non-terminal; the timer stops itself when nothing needs checking and clears on unmount.
- Polling **stops on terminal states** `COMPLETED`, `FAILED` and `DUPLICATE` — mirroring
  `ProcessingOutcome.ALREADY_TERMINAL` in the backend — and on **404** (the entry stays visible
  as "Not found" with an explanation).
- **Failures back off** 2 s → 4 s → 8 s → 15 s (capped); after **5 consecutive failures** polling
  pauses with a message and a manual **Retry** button resumes it.
- Job IDs persist in `localStorage` (`eddp.tracked-jobs.v1`, newest first, capped at 20), so
  tracking resumes after a refresh. Corrupt or malformed entries are dropped on load; **Remove**
  deletes an entry and its stored id.
- Accessibility: one sr-only `role="status"` live region announces actual status transitions only —
  never each poll cycle — and per-row actions carry filename-based accessible names.

## Processing results (Phase 3)

The same `GET` response carries an optional `processing` object (`started_at`, `finished_at`,
`sha256`, `size_bytes`, `failure_code`) — a safe subset of the internal metadata; the lease, token
and object version are never sent. It is `null` until an attempt records results, so nothing
changes for pending or in-flight jobs, and all Phase 1/2 response keys stay identical.

- **Completed** rows show the finish time and duration, the processed size, the full SHA-256
  (monospaced, wrapping) and "Format validation passed".
- **Failed** rows show a plain-language reason for each payload-free backend failure code
  (`EMPTY`, `TOO_LARGE`, `SIZE_MISMATCH`, `INVALID_FORMAT`, `FORMAT_MISMATCH`, `RESOURCE_LIMIT`);
  a future unknown code falls back to displaying the code itself.
- No extra requests: results arrive on the poll that reports the terminal status, which is also
  where polling stops — layout, polling and storage behaviour are otherwise unchanged.

## Networking and CORS

| Traffic                          | Path                                                                        | Mechanism                                                 |
| -------------------------------- | --------------------------------------------------------------------------- | --------------------------------------------------------- |
| Browser → API                    | `localhost:5173` → `/api` → `127.0.0.1:8000`                                | Vite dev proxy (same-origin, no CORS)                     |
| Browser → API (direct, optional) | any origin → `:8000`                                                        | FastAPI `CORSMiddleware`, gated by `CORS_ALLOWED_ORIGINS` |
| Browser → storage                | `localhost:5173` → `127.0.0.1:4566` (normal stack) or `:4567` (event stack) | S3 bucket CORS, gated by `S3_CORS_ALLOWED_ORIGINS`        |

- Compose defaults both settings to `["http://localhost:5173"]` (the local Vite origin). Both
  default to closed (`[]`) in `.env.example` and are validated to reject wildcards, paths and
  credentials — see `bootstrap/settings.py`.
- The **event-enabled stack** (`compose.lambda.yaml`) provisions the same bucket CORS during
  `infra/events/bootstrap.py`, so later bootstraps cannot silently drop it.
- Set `VITE_API_BASE_URL=http://127.0.0.1:8000` only if you want to bypass the proxy and exercise
  the CORS middleware directly.

## Validation rules (client-side, mirrors the backend)

| Rule             | Value                                        | Backend counterpart              |
| ---------------- | -------------------------------------------- | -------------------------------- |
| Content types    | `application/pdf`, `image/png`, `image/jpeg` | `upload_allowed_content_types`   |
| Maximum size     | 10 MiB                                       | `upload_max_file_size_bytes`     |
| File name length | ≤ 255 characters                             | `CreateDocumentRequest.filename` |
| Empty file       | rejected                                     | presigned `content-length-range` |

Client validation is a fast-feedback layer only; the presigned policy and the processing
validator remain authoritative.

## Structure

```
src/
├── App.tsx                    # Page shell: header, hero, upload + tracking sections
├── main.tsx                   # React entry point (StrictMode)
├── index.css                  # Tailwind v4 import + theme
└── features/documents/
    ├── types.ts               # Response types mirrored from the Pydantic schemas
    ├── api.ts                 # createUpload + getJob fetch wrappers
    ├── validation.ts          # Pure client-side preflight helpers
    ├── tracking.ts            # Pure status/backoff/localStorage rules
    ├── useUpload.ts           # Upload state machine: validate → authorize → XHR progress
    ├── useDocumentTracker.ts  # Polling, persistence, retry/remove, announcements
    ├── UploadCard.tsx         # Dropzone, progress, success and error panels
    ├── RecentDocuments.tsx    # Tracked list, status badges, results, Retry/Remove controls
    └── *.test.ts(x)           # 49 focused unit/component tests
```

No router, global state library or data-fetching framework: two HTTP endpoints do not justify them.
New abstractions are added only when a second real feature needs them.

## Testing

`npm test` runs six suites with mocked `fetch` and a fake `XMLHttpRequest`:

- `validation.test.ts` — accepted/rejected types, size, name rules, byte formatting
- `api.test.ts` — exact request shapes (the Pydantic schemas forbid extra keys), fixed backend
  `detail` handling, 404/`getJob` behavior, never echoing FastAPI validation arrays
- `tracking.test.ts` — terminal statuses for all five backend states, backoff math, failure-code
  explanations for all six backend codes (plus unknown-code fallback), duration formatting,
  defensive localStorage parsing (corrupt/duplicate/oversized data), timestamp formatting
- `useDocumentTracker.test.ts` — resume from localStorage, terminal stop, transition-only
  announcements, failure backoff → pause → retry, 404 handling, remove cleanup, unmount cleanup,
  list cap (fake timers throughout)
- `RecentDocuments.test.tsx` — badges for every status, paused/missing explanations, processing
  results (digest/size/timing/validation), failure reasons, in-progress suppression, accessible
  Retry/Remove controls, polite live region
- `UploadCard.test.tsx` — happy path with progress events and 204 confirmation plus the tracking
  handoff, authorization state, invalid/oversized rejection, drag-and-drop, expired-link (403)

All tests are offline; no emulator or Docker is required.

## Known limitations (Phase 3 scope)

- Results stop at metadata: no extracted text, page previews, malware scanning or history view.
- The API has no authentication; this is a local development interface.
- The 10 MiB client limit mirrors the backend default; a reconfigured backend is not yet
  advertised through an API endpoint.
- Tracking state is per-browser-tab storage only: another browser or machine sees no history, and
  `DUPLICATE` cannot be produced locally until backend deduplication exists.
- One shared 2 s interval is used for simplicity; very large tracked lists would benefit from
  staggered scheduling.
