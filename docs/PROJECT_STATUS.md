# Project status

## Milestone 3 — secure local S3 uploads

Implemented while preserving all Milestone 2 endpoints and the save/get repository contract:
- `POST /api/v1/documents/uploads` validates metadata, signs a POST policy, saves the pending
  job/reference, and only then returns authorization with `Cache-Control: no-store`.
- UploadAuthorizer is a narrow application Protocol; boto3 stays in infrastructure/bootstrap.
  Infrastructure adapters explicitly declare their Protocol implementations for readability.
- Server-controlled `quarantine/{job_id}/{random_id}` keys, exact signed Content-Type/file size,
  configurable MIME allowlist (PDF/PNG/JPEG), 10 MiB default maximum, 300-second default expiry.
- Optional immutable object references are serialized additively in DynamoDB. Existing rows
  without the attribute remain readable; no signed URLs, policies, or signing fields are saved.
- Idempotent S3 provisioning in the existing one-shot service: private dedicated bucket,
  all Block Public Access flags, BucketOwnerEnforced, no bucket policy, SSE-S3 configuration,
  and empty-by-default CORS allowlist with explicit origins only.
- Floci remains pinned to 2.4.0 with S3 authentication enabled and supported dummy test/test
  credentials. Provisioning uses floci:4566; host-facing signing uses localhost:4566 without
  rewriting URLs. The shared emulator gateway is published only on 127.0.0.1:4566.
- No confirmation, renewal, deduplication, content parsing, processing, messaging, or webhooks.

### Verification — Milestone 3 (2026-11-07 local date)
- Git working tree was clean before implementation; no commit/push or volume deletion performed.
- `uv sync`: passed; added S3 typing support while preserving Python 3.14+ and uv_build.
- `uv run pytest`: **106 passed, 18 skipped** on host Python 3.14.7. All 18 skips are opt-in
  Floci integration tests, including the test that exposes the SSE emulator limitation below.
- `docker compose --profile test run --build --rm tests`: **123 passed, 1 xfailed** on Linux
  Python 3.14.10. This includes the existing Milestone 2 suite and real multipart HTTP uploads.
- Floci tests verified size/type/key conditions, signature/policy tampering, expiry, unsigned
  write rejection, anonymous read rejection, replay behavior, private bucket settings, old
  record serialization, and persistence of the object reference. Authentication stayed enabled.
- One **strict expected failure**: Floci 2.4.0 stores/reports bucket AES256 configuration but
  POST-created objects omit ServerSideEncryption metadata. Actual object encryption at rest
  is **not verified**. The AWS expectation remains in a separate test; no security check was
  silently disabled. This requires independent real-AWS verification before production claims.
- `uv run ruff check .`: passed.
- `docker compose --profile test run --rm tests uv run --no-sync ruff check .`: passed.
- `docker compose config --quiet`: passed.
- `git diff --check`: passed; Git emitted Windows line-ending conversion warnings only.
- `uv run python infra/local/verify_upload.py`: passed against the actual API-issued localhost
  URL. Verified direct upload, anonymous denial, retained job responses, and identical object
  bytes after Floci recreation with the existing volume retained and bootstrap rerun.
- `uv run python infra/local/verify_persistence.py`: passed; API restart and Floci recreation
  still retain metadata-only jobs, confirming the Milestone 2 workflow.
- A privileged read-only local inspection found **two pre-Milestone-3 records** in the retained
  DynamoDB table; both were readable through the current GET API without new response fields.
- Initial Docker absence was resolved by starting Docker Desktop. A unit-test environment
  isolation issue was corrected; the final container result above has no unexpected failures.
- API and Floci were left running, healthy, on loopback ports 8000 and 4566; the existing
  volume and verification jobs/objects were retained.

### Current limitations / public-deployment blockers
Local development only. Add authentication, ownership checks, quotas, and rate limits before
public exposure; CORS and a private bucket do not secure an unauthenticated issuer. Presigned
POST can be replayed until expiry to overwrite the same key. File size and MIME metadata do
not prove file format/safety; future trusted processing must inspect bytes and malicious content.
No confirmation/renewal exists and all jobs remain PENDING. Unused jobs/objects are retained;
there is no cleanup worker. Floci does not establish AWS IAM, at-rest encryption, or power-loss
durability guarantees. API CORS remains unchanged; only bucket CORS is configurable.

See `docs/decisions/0002-secure-uploads.md` and README for workflow and security tradeoffs.

## Verified baseline before Milestone 2
- FastAPI exposes metadata-only document job creation/retrieval and `/health`.
- Jobs have UUIDs, UTC timestamps, and initial `PENDING` status.
- One documents module separates API, application, domain, and infrastructure.
- `JobRepository` is a Protocol with `save` and `get`; runtime wiring uses in-memory storage.
- Eight existing test functions cover service behavior and HTTP contracts.
- S3 uploads, queues, workers, deduplication, and webhooks are not implemented.

## Milestone 2
Implemented and verified locally:
- boto3 DynamoDB adapter replaces runtime in-memory wiring; the Protocol/service/domain remain unchanged.
- Table key: string `pk = JOB#{job_id}`. `HASH#{sha256}` is reserved only; no deduplication exists.
- UUID/status/timestamp mapping, strongly consistent reads, and explicit unavailable/corrupt-data errors.
- Pydantic environment settings, bounded SDK retries/timeouts, and payload-free contextual logging.
- Existing endpoints, response fields, validation, and legacy filename alias are preserved.
- Non-root API image, pinned Floci 2.4.0, persistent named volume, and idempotent bootstrap service.
- Separate runtime/bootstrap IAM examples; no real AWS resources or IAM policies were deployed.
- Isolated in-memory HTTP tests, SDK-stub unit tests, opt-in Floci integration tests, and
  an HTTP-based API restart / Floci recreation verification script.

## Verification results — 2026-11-05
- `uv sync`: passed; lockfile refreshed and runtime/development dependencies installed.
- `uv run pytest`: **53 passed, 4 skipped** on Python 3.14.7. All eight original tests passed.
- The four host-run skips are opt-in Floci cases; all four subsequently passed inside Compose.
- `uv run ruff check .`: passed.
- `uv run ruff format --check --exclude routes.py src tests infra`: passed (33 files).
  The broader format check also flagged an existing line-ending issue in unchanged
  `bootstrap/routes.py`; it was left untouched to avoid an unrelated edit.
- `docker compose config --quiet`: passed.
- `docker compose --profile test config --quiet`: passed.
- `git diff --check`: passed (Git emitted only Windows line-ending conversion warnings).
- Docker was initially stopped; `docker desktop start` succeeded and enabled runtime checks.
- `docker compose --profile test run --build --rm tests`: **57 passed** on Linux Python 3.14.10,
  including all Floci integration cases. Runtime and test image builds succeeded.
- `docker compose --profile test run --build --rm tests uv run --no-sync ruff check .`: passed.
- `uv run python infra/local/verify_persistence.py`: **passed**. A real HTTP-created job
  retained its identical response after API restart, Floci container recreation with the
  named volume retained, and another bootstrap run.
- The first Docker-enabled persistence run exposed a connection-reset race in health polling;
  the verifier now retries transient HTTP connections with bounded attempts, with two unit tests.
- `docker compose exec -T api id -u`: **10001** (non-root).
- `docker compose ps`: API and Floci healthy; only API port `127.0.0.1:8000` is published.

## Repeatable verification
1. Start Docker Desktop with Linux containers.
2. Run `uv sync`, `uv run pytest`, and `uv run ruff check .`.
3. Run `docker compose --profile test config --quiet`.
4. Run `docker compose --profile test run --build --rm tests`.
5. Run `docker compose --profile test run --rm tests uv run --no-sync ruff check .`.
6. Run `uv run python infra/local/verify_persistence.py` and confirm the PASS output.

## Milestone 2 limitations (historical)
Local restart persistence is verified, not host power-loss durability or actual AWS IAM enforcement.
POST is not idempotent; write timeouts can be ambiguous. `/health` is liveness-only. Explicit
volume deletion removes local data. No uploads, processing, deduplication, queues, or callbacks
are part of this milestone. See `docs/decisions/0001-local-dynamodb.md` for tradeoffs.
The local API and Floci stack, named volume, and verification jobs were left intact; no
volume deletion, commit, or push was performed.

## Verification at start of this milestone
- Git working tree was clean.
- uv 0.13.6 is installed.
- Docker CLI is installed, but the Docker Desktop Linux daemon is unavailable.
- At that point, milestone tests had not yet been executed; current outcomes are listed above.

See `AGENTS.md` for architecture, Python standards, and the required verification workflow.
