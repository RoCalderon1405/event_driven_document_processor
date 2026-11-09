# Explicit local event stack

The normal `compose.yaml` is unchanged: its API and old upload tests do not consume events.
Run the opt-in event stack with the existing Lambda overlay:

```sh
uv sync --locked
docker compose -p eddp-lambda-probe -f compose.lambda.yaml --profile processing config --quiet
docker compose -p eddp-lambda-probe -f compose.lambda.yaml --profile processing up --build -d processing-api
uv run python -m infra.events.verify
```

API: http://localhost:8001/docs. Signed uploads target http://localhost:4567. Both ports are
loopback-only. Default resource names are event-document-jobs / event-document-uploads, processing
queue/function/role document-processing and DLQ document-processing-dlq. The normal stack remains
separate on 8000/4566. Docker Desktop must use Linux containers; the supported package target is
Linux/amd64 Python 3.14. Only the trusted emulator receives the privileged Docker socket.

Reconcile infrastructure again without resetting any data:

```sh
docker compose -p eddp-lambda-probe -f compose.lambda.yaml run --build --rm processing-bootstrap
```

The artifact is built from locked Linux wheels in the official pinned Lambda image and installed
as a versioned private S3 ZIP outside quarantine/. Processing delegates to Phase 2's existing core.
This is still local development: dummy credentials/IAM emulation and format validation are not
proof of production authorization, encryption, or malware freedom.

## Automated checks

```sh
uv run pytest
uv run ruff check .
docker compose --profile test run --build --rm tests
docker compose -p eddp-lambda-probe -f compose.lambda.yaml run --build --rm lambda-tests
docker compose -p eddp-lambda-probe -f compose.lambda.yaml run --build --rm event-tests
```

Event tests require `RUN_EVENT_TESTS=1`, supplied only by event-tests. They use unique disposable
buckets/tables/roles/queues/functions and clean up their own resources, not development data.
Real crash/timeout/DLQ tests intentionally wait for visibility expiry and take several minutes.
Their validated accelerated timing is timeout 8 seconds, lease 30 seconds, visibility 48 seconds,
three receives. Development defaults are timeout 150, lease 180, visibility 900, five receives.
Do not shorten visibility below the validated timeout/lease relationships to make tests faster.

`infra/events/verify.py` uses the real deployed API over HTTP and retains its PDF/PNG/JPEG
verification jobs/versions. The automated tests use the same real API route through TestClient
with fixture-only resource wiring and perform actual multipart HTTP uploads to Floci.

## Stop safely

```sh
docker compose -p eddp-lambda-probe -f compose.lambda.yaml stop processing-api lambda-floci
```

The separate lambda-data volume and all development objects remain retained. Never use volume
deletion/prune commands as bootstrap or test cleanup. Phase 1 probes now run on the same persistent
overlay emulator but still create and remove only their own disposable resources. See ADR 0004
and PROJECT_STATUS.md for tested behavior and remaining environment limits.
