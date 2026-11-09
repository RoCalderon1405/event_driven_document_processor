# Floci 2.4.0 / Python 3.14 compatibility gate

These are disposable **synthetic infrastructure probes**, not a ProcessingService or a
production event workflow. The probes remain separate from the Phase 3 business handler; the
same explicit overlay now also offers opt-in processing and event-test profiles.

## Run

Prerequisites: Docker Desktop Linux containers (Windows) or a Linux Docker Engine, Docker
Compose v2, network access to pull images, and an accessible Docker daemon socket.

```sh
uv sync --locked
docker compose -p eddp-lambda-probe -f compose.lambda.yaml config --quiet
docker compose -p eddp-lambda-probe -f compose.lambda.yaml run --build --rm lambda-tests
docker compose -p eddp-lambda-probe -f compose.lambda.yaml stop lambda-floci
```

The compatibility file is usable standalone. It adds its own `lambda-floci` service, network,
separate persistent lambda-data volume and test runner; it does not override or restart the normal
development `floci` service. Phase 3 publishes the authenticated gateway only on loopback 4567
and its optional API on 8001. Neither API nor test runner receives the Docker socket. The fixture
SDK clients use explicit dummy test/test credentials and refuse non-local endpoints.

The default socket is `/var/run/docker.sock`; `DOCKER_SOCKET` can name a different local daemon
socket. This is **daemon-level privilege**, even if a mount were made read-only. Run only trusted
probe code on disposable/local development hosts. Do not mount the socket into a normal API.

The official Lambda Python 3.14 image is pinned in `probe-runtime.yaml`. Floci's Quarkus config
location loads this map. The Lambda runtime joins the named probe network and calls back to
`lambda-floci` on internal Runtime API ports; no host callback ports are needed. Uploaded ZIPs
avoid Docker-host bind paths and Windows drive-letter translation for function code.

Linux GitHub-hosted runners should use the same Linux socket/network pattern and command,
but **no GitHub Actions runner was executed in Phase 1**. This is not a verified CI result.
The tested platform was Windows Docker Desktop with its Linux/amd64 Engine. ARM64, remote/rootless
daemons, and native Ubuntu-host behavior require separate verification. No workflow is added.

## Probes and evidence

- `lambda_probe.py`: deterministic ZIP assembly from the locked pure-Python SDK packages,
  endpoint guard, and deadline-based polling. No FastAPI/domain/application modules are packaged.
- `lambda_handler.py`: reports Python/SDK and per-process invocation counters; reads exact
  synthetic S3 versions into a bounded digest; writes synthetic DynamoDB receipts; deliberately
  reports selected SQS failures or raises a fixed exception. No document jobs/statuses are touched.
- `tests/compatibility/conftest.py`: creates unique `lambda-probe-*` roles, tables, functions,
  private versioned buckets, queues and mappings; tears down only the resources it registered.
- `test_lambda_floci.py`: five real gates, with sanitized evidence printed by `pytest -s`:
  cold/warm Python 3.14 reuse; versioned POST event metadata plus authenticated Lambda reads;
  mixed-batch retry of only the failed message; partial-failure and thrown-error DLQ redrive.

The synthetic retry tests use a five-second visibility timeout, five-second function timeout,
and three receives to keep the gate fast. Visibility is not less than function timeout, but
production should use the larger AWS-recommended retry margin (typically at least six times
function timeout, plus batching window). Tests warm the SQS functions before enabling mappings.
These are not production timeout recommendations, nor proof of cold-start SQS visibility handling. Production-scale
concurrency, conditional processing leases, restart recovery, and fault injection remain later work.

S3 notifications are checked separately from the SQS handler using the same disposable emulator.
No complete document-processing chain is installed on the development bucket. Lambda reads an
older event-selected version after a second POST overwrites the same key, and writes the selected
version/digest to the disposable table. Anonymous read/write and tampered signature attempts must
fail while `FLOCI_SERVICES_S3_ENFORCE_AUTH=true` remains enabled.

Local dummy credentials are explicitly injected under custom PROBE_* names for the synthetic
handler. This proves credential/signature compatibility and SDK connectivity, **not execution-role
credential delivery, least-privilege IAM enforcement, real AWS security, or encryption at rest**.
The existing SSE-S3 expected failure remains unchanged in the Milestone 3 suite.

Fixtures delete only their unique AWS-shaped test resources. No Docker volume deletion or pruning
commands are used, and the development persistent volume is never mounted into this emulator.
Floci can create its own namespaced Lambda code-cache volumes for large ZIPs; do not prune them
globally. Stop the probe service when done. A crash may leave probe resources/log groups until
that emulator is explicitly reconciled; do not use broad cleanup commands against either stack.

## Baseline checks

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
docker compose config --quiet
docker compose --profile test run --build --rm tests
```

Lambda gates require `RUN_LAMBDA_COMPATIBILITY=1` and `LAMBDA_PROBE_ENDPOINT`; the standalone
Compose runner supplies both. The normal suite skips those five gates; it does not silently
pretend that Lambda was tested. Existing repository formatting differences are reported, not
fixed or excluded by this phase. See `docs/PROJECT_STATUS.md` for actual outcomes.
