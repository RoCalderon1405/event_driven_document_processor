# Changelog

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
