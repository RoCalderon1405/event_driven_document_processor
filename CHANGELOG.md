# Changelog

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
