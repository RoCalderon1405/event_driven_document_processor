# Project status

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

## Remaining limitations
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
