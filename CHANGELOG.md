# Changelog

## Unreleased — GHCR continuous delivery

- Added canonical SemVer tag releases that reuse the complete existing CI workflow before publishing.
- Build and inspect the non-root Linux/amd64 `runtime` target, never the Dockerfile's final test/
  bootstrap target. Publish version/full-commit tags with verified matching GHCR digests in the summary.
- Limit package writes to a separate publishing job using GITHUB_TOKEN; prevent workflow overwrites
  through duplicate checks, remote-tag provenance checks and repository-wide release serialization.
- Document tag/package access rules, partial-release behavior, local checks and the distinction between
  configured delivery and an actual hosted release. No AWS deployment or automatic Git operations.

## Unreleased — Milestone 4 Phase 4

- Added SHA-pinned, read-only GitHub Actions CI for pull requests and master pushes, using Python
  3.14, uv 0.13.6, locked dependencies and complete pytest/Ruff lint/format gates.
- Added reusable isolated Docker gates with ephemeral Floci state, no published ports/development
  mounts, explicit native Lambda compatibility/event suites, exact-project cleanup and sanitized logs.
- Added CI isolation/result-enforcement tests, reproduction/security documentation and ADR 0005.
  The existing strict SSE xfail is preserved; unexpected skips/new expected failures fail Docker CI.
- Resolved the 11-file Ruff baseline as a separate AST-equivalent formatting patch with LF checkout
  policy. No commits, pushes, CD, Coveralls, React or production credentials were introduced.

## Unreleased — Milestone 4 Phase 3

- Added strict S3 notification decoding and a thin SQS Lambda adapter delegating to the existing
  ProcessingService. Outer-message partial failure reporting preserves active-claim retries and
  safe replay of successful nested records without duplicating business logic.
- Added opt-in idempotent queue/DLQ/role/Lambda/mapping provisioning, quarantine/ create notifications,
  source-scoped policies and notification/policy merging that retains unrelated entries.
- Added locked native Linux Python 3.14 Lambda artifact packaging in the pinned official runtime,
  private versioned artifact deployment, validated timeout/lease/visibility budgets and narrow IAM
  examples. Normal API contracts, processing transitions and old test buckets remain unchanged.
- Extended the explicit Lambda overlay with separate persistent storage, loopback gateway/API,
  event-test runner and host-facing verification. Socket access remains emulator-only.
- Added event decoding/acknowledgement/packaging unit tests and isolated real event-chain tests,
  including duplicate/order/concurrency, partial messages, native formats, crash/timeout recovery,
  poison/DLQ delivery and repeated bootstrap. Actual outcomes are recorded in PROJECT_STATUS.md.
- Added ADR 0004 and event-stack instructions. No CI/GHCR, webhook, AI or document deduplication added.

## Unreleased — Milestone 4 Phase 2

- Added shared ProcessingService and narrow processing-store, versioned-reader and validator ports;
  kept HTTP contracts and JobRepository.save/get unchanged. No production event consumer added.
- Added first-claimed-version selection, unique claim tokens, expiring leases and conditional
  DynamoDB UpdateItem fencing for same-version recovery and terminal success/permanent failure.
- Added internal declared lengths and optional backward-compatible processing metadata, SHA-256,
  bounded streaming/temp-file staging, exact-version S3 reads and sanitized permanent failure codes.
- Added real PDF/PNG/JPEG validation using maintained pikepdf and Pillow, with child-process
  deadlines, Linux memory/CPU budgets, image/page/object limits and no malware-free claims.
- Enabled non-destructive local bucket versioning; adapted disposable upload-fixture cleanup for
  exact versions. Added separate undeployed processor IAM example and environment policy settings.
- Added service, adapter, parser and bootstrap unit tests, genuine generated fixtures and isolated
  Floci race/recovery/version-specific tests. Preserved the Phase 1 compatibility implementation.
- Documented module connections, retry semantics, limitations and Phase 3 packaging requirements
  in README and ADR 0003. Actual verification is recorded in PROJECT_STATUS.md.

## Unreleased — Milestone 3

- Added a compatible create-and-authorize upload endpoint with private, short-lived presigned
  POST policies, exact MIME/file-length constraints, opaque quarantine keys, and no-store responses.
- Added a narrow UploadAuthorizer Protocol, explicit adapter implementations, and immutable
  optional object references with backward-compatible DynamoDB serialization. Signing fields
  are excluded from persistence and authorization repr output.
- Added validated S3/upload settings, closed-by-default browser CORS, separate internal/public
  endpoints, and sanitized signing failures while preserving metadata-only API behavior.
- Extended local bootstrap with idempotent private-bucket provisioning, Block Public Access,
  BucketOwnerEnforced, SSE-S3, and CORS configuration. Enabled strict S3 authentication in
  pinned Floci 2.4.0 using test/test credentials, with the gateway published on loopback only.
- Added unit and real-HTTP Floci upload security tests and a host-facing upload/recreation
  verification script. Documented replay, untrusted MIME metadata, and public-deployment blockers.

## Unreleased — Milestone 2

- Added a boto3 DynamoDB repository with `pk = JOB#{job_id}`, strongly consistent reads,
  explicit item mapping, and reserved (unused) `HASH#` namespace.
- Replaced runtime in-memory wiring while retaining the original repository Protocol,
  service, API schemas, and in-memory test adapter.
- Added Pydantic environment settings, bounded SDK retries/timeouts, safe persistence
  error responses, and contextual logging without document payloads or credentials.
- Added non-root Python containers and Docker Compose with pinned Floci 2.4.0,
  named-volume persistence, health-based ordering, and idempotent DynamoDB bootstrap.
- Added focused SDK-stub, configuration, provisioning, HTTP-error, and opt-in Floci tests,
  plus an HTTP-based API/Floci restart-persistence verification script.
- Added architecture guidance, status tracking, a storage decision, and separate
  least-privilege IAM policy templates. Refreshed the uv lockfile without changing uv_build.

Verification outcomes and environment limitations are recorded in `docs/PROJECT_STATUS.md`.
