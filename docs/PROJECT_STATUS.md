# Project status

## README presentation refresh

- Reorganized README into a concise portfolio landing page with nine requested sections, a hero,
  static stack/status badges, event-flow diagram, quick start and links to deeper documentation.
- Preserved detailed configuration, API examples, storage/processing invariants and local safety
  guidance in `docs/DEVELOPMENT.md`; adjusted relative links for its new location.
- Passed: reusable quality runner (locked sync, offline pytest, Ruff lint/full formatting), Compose
  configuration validation, local documentation-link/section checks and final whitespace check.
- Not rerun for this documentation-only change: Docker integration/event suites and persistence
  restart verification. Existing results below remain historical evidence, not new executions.
- No hosted CI/AWS validation or rendered GitHub/browser preview was performed. No code, runtime
  configuration, credentials, commits or pushes were changed by this refresh.

## Milestone 4 Phase 4 — secure GitHub Actions CI

Implemented as uncommitted working-tree changes, preserving the prior Phase 3 work. No commit,
push, deployment, GHCR publication, Coveralls, React or production credentials. The actual remote
default branch was confirmed as **master**, not assumed to be main.

### Files and responsibilities
- `.github/workflows/ci.yml`: PR/master-push/manual triggers, read-only contents permission,
  SHA-pinned checkout/Python/uv actions, no persisted checkout credentials or shared caches,
  concurrency cancellation, bounded Ubuntu 24.04 quality and Docker jobs, always cleanup.
- `infra/ci/run.py`: same stdlib entrypoint for hosted/local quality and Docker gates; sanitizes
  the child environment and logs, generates exclusive per-run Compose projects, validates resolved
  configuration, builds all relevant images and performs exact-project cleanup without volume removal.
- `infra/ci/compose.regression.yaml`, `compose.events.yaml`, `empty.env`: CI-only removal of ports/
  persistent mounts, memory/tmpfs emulator state, isolated Lambda runtime namespace/network/prefix,
  no inherited developer `.env`. Base Compose files remain unchanged by Phase 4.
- `infra/ci/pytest_gate.py`: explicit Docker execution enforcement; no skips/new xfails accepted.
  Existing exact strict SSE assertion xfail remains untouched, including unexpected-pass failure.
- `tests/unit/test_ci.py`: 27 tests for environment isolation, fixed command construction, safe
  config/cleanup, failure cleanup, payload-free logs and result enforcement. Five spawn real pytest
  to verify pass/fail/skip/xfail/xpass exit behavior, not only synthetic reports.
- `infra/ci/README.md`, ADR 0005, README and CHANGELOG: behavior, trust/logging tradeoffs, commands,
  manual GitHub approval/branch settings and truthful separation of hosted versus local evidence.
- `.gitignore` / `.dockerignore`: exclude only the generated CI cleanup state from version/build input.

### Separate formatting-only baseline
The 11 baseline files were clean before formatting. Ruff formatting changed no Python AST in any
of them; no business edits were mixed in. `.gitattributes` adds consistent Python LF checkout policy.
`docs/changes/formatting-baseline.patch` contains precisely those 11 files plus that policy, separate
from all CI and earlier Phase 3 changes. Its `git apply --cached --check` passed; the index remains
untouched. `docs/changes/formatting-baseline.md` lists every path and user-operated staging commands.
`routes.py` needed only a final newline. Full formatting now passes without exclusions or weakened rules.

### Actual verification in this environment
- `uv sync --locked` and the reusable **quality** command passed with uv 0.13.6 / Python 3.14.7.
- Final direct offline pytest: **247 passed, 57 intentional opt-in skips**. The skip counts
  are not claimed as executed integration evidence. All **27 new CI tests passed**, including the
  five actual pytest subprocess enforcement cases.
- Full Ruff lint and `ruff format --check .` passed (**95 files already formatted**).
- `docker compose config --quiet` passed. The full reusable **Docker** command passed: both override
  configurations validated, all runtime/test/native Lambda/event images built, isolated regression
  **284 passed / 0 skipped / 1 known SSE xfailed**, compatibility **5 passed / 0 skipped**, and real
  event chain **9 passed / 0 skipped**. Both exact-project cleanup commands passed. This initial
  image contained 22 CI tests. The final isolated regression rerun, including all 27 CI tests and
  the final plugin, passed **289 / 0 skipped / 1 known SSE xfailed**, with scoped cleanup passed.
- The required normal development Docker command also passed: **289 passed, 14 skipped,
  1 existing SSE xfailed**. Its 14 skips are the separately invoked compatibility/event suites.
- `uv run python infra/local/verify_persistence.py` passed after the formatting/CI changes, retaining
  the verification job across API restart and Floci container recreation without volume deletion.
- The formatted `infra/local/verify_upload.py` also passed: signed upload, anonymous denial, legacy
  compatibility and object persistence after Floci recreation.
- Live read-only inspection during the CI event gate confirmed no published ports, no Compose data
  volumes, and only two bind mounts on lambda-floci (socket and read-only runtime YAML). The test
  container and normal CI Floci had no bind/data mounts. Development project names were not reused.
- Post-run inspection confirmed the complete CI run removed its containers/networks and cleanup
  state. It also exposed **eight isolated Floci Lambda code-artifact volumes** retained by the
  launcher's implementation, with the exact CI `floci_namespace` label. They were not deleted:
  no persistent-volume removal is authorized or needed for correctness. No development data volume
  was reused/deleted. This local disk-cost limitation is documented; hosted runner disposal handles it.
- Repeated cleanup with no state passed as a safe no-op. Normal development API/Floci remain healthy.
- Actionlint **1.7.12** validated the workflow. Its official Windows/amd64 release archive was
  checked against SHA-256 `6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9`
  before execution. Action commit pins were independently resolved upstream and action.yml inputs read.
- `git diff --check` passed with Git line-ending warnings only. No staged changes, commit or push.

### Hosted execution and manual settings
**Hosted run blocked/not executed**: the new workflow exists only in the working tree and cannot be
dispatched until published; committing/pushing is prohibited by the request. `gh` is also unavailable.
Actionlint and local Linux containers are not a successful GitHub-hosted Ubuntu run.

After user publication, enable Actions/allow the three pinned upstream actions, retain read-only
workflow permissions, require fork-workflow approval, and run the workflow. Then protect master with
the actual **Python quality** and **Docker integration** required checks. No repository secrets or
deployment credentials/settings are required. Do not use persistent/self-hosted runners: the Lambda
emulator controls Docker, so runner disposability is the privilege boundary. See infra/ci/README.md.

### Remaining limits
The existing SSE metadata xfail still does not prove at-rest encryption. Real AWS IAM/workload-role
delivery and GitHub-hosted runner behavior remain unverified. Cold image pulls or upstream registry
outages may hit bounded timeouts; base Python/uv/Floci image tags are not newly digest-pinned by this
phase (the actual Lambda runtime already is). Raw test/build diagnostics are intentionally withheld
from CI output; failures must be reproduced privately with emulator credentials. Hard local interruption
can leave scoped Docker resources; retain `.ci-state.json` and retry cleanup, never prune local data.

## Milestone 4 Phase 3 — explicit S3/SQS/Lambda event integration

The normal API contracts, Phase 2 application/domain/infrastructure processing code and Phase 1
probe implementations remain unchanged. The opt-in Lambda overlay connects real versioned upload
notifications to SQS and a thin Python 3.14 handler. No GitHub Actions, GHCR, webhooks, OCR, AI or
cross-document deduplication was added. The initial working tree was clean; no commit/push or
persistent-volume deletion/prune was performed.

### Files, connections and configuration
- `bootstrap/lambda_handler.py`: SQS batch adapter, remaining-time guard, sanitized outcome logs,
  guarded local dummy credentials and delegation to the existing ProcessingService factory.
- `documents/events/s3_events.py` / `__init__.py`: bounded strict S3 body decoding, one-time key
  unquoting, opaque version IDs, quarantine job UUIDs and matching S3 test-event handling.
- `bootstrap/event_settings.py`: shared Pydantic delivery settings. Default record budget **133 s**
  < Lambda timeout **150 s** < claim lease **180 s**; visibility **900 s** covers both six timeouts
  and lease expiry plus five seconds. Batch size **2**, batching window **0**, **5 receives** before
  DLQ, source retention **4 days** (existing longer periods retained), DLQ retention **14 days**.
- `infra/events/bootstrap.py`: explicit local-only provisioning/reconciliation for queues/DLQ,
  scoped policies/role/log group, private versioned artifact, Lambda, mapping and notifications.
  It merges owned policy Sid/notification ID, preserves unrelated notification kinds/statements,
  preserves other DLQ sources, and never deletes/recreates resources or weakens an explicit DLQ deny.
- `infra/events/package.py`, `Dockerfile`: deterministic full locked runtime packaging in the
  official pinned Linux/amd64 Python 3.14 Lambda image, retaining native libraries and layout.
  Artifact versions live outside quarantine/ and cannot recursively trigger processing.
- `compose.lambda.yaml`: optional processing bootstrap/API and event-test targets; separate
  persistent lambda-data volume, loopback gateway **4567**, optional API **8001**. Only lambda-floci
  receives the Docker socket. Normal Compose/API/volume stay separate on **4566/8000**.
- `infra/events/verify.py` / README: real host-facing HTTP verification and reproducible commands.
- `tests/events/`: real event-chain tests, scoped resources and a test-only crash/timeout wrapper;
  production artifacts/handlers contain no fault switches or diagnostic backdoor action.
  `tests/unit/test_event_handler.py`: 30 offline transport/budget/merge/packaging/fault-fixture cases.
- `infra/iam/processing-policy.json`, new queue/provisioning examples: separate job/versioned-read,
  SQS-consumption, source-scoped S3 delivery, log-stream and privileged provisioning/PassRole roles.
  API upload permissions are unchanged; examples are not deployed or verified AWS authorization.
- `pyproject.toml`: explicit event marker and root import path for local infrastructure test tools;
  no dependency/lockfile change needed. README, CHANGELOG, compatibility README and ADR 0004 updated.

### Verified outcomes
- Actual API-issued presigned POST notifications completed PDF/PNG/JPEG jobs in the official Lambda
  runtime with independently checked SHA-256, actual lengths and exact S3 version IDs. This proves
  pikepdf/Pillow native decoding in Lambda, not merely successful imports in the Linux test runner.
- First complete event run: **7 passed, 2 failed**. Passing gates covered all genuine formats,
  malformed documents becoming FAILED, duplicate/delayed/reversed/concurrent delivery, nested
  records/outer-ID partial failures/S3 test events, active-claim retry and expiry recovery,
  poison/unavailable-version DLQ delivery, and repeated bootstrap preserving data/notifications.
  The two fault tests did not reach a claim because their test-only wrapper indexed an empty S3
  test notification. The wrapper was corrected to find real nested requests; a regression unit
  case was added. The corrected full event suite then passed **9/9 in 462.28 s**, with no skips
  or expected failures. Both real worker exit and timeout cases committed an initial claim and
  subsequently completed the same version with a new fencing token after redelivery.
- The reversed/concurrent gate was strengthened with distinct, equal-length valid PDF versions;
  its separate rerun **passed**, including the selected newer version's independent hash.
- Verified final-suite artifact: **48,730,086 compressed bytes / 121,787,023 unpacked bytes**, including
  Linux pikepdf/Pillow .so files and no Windows .pyd files; below Lambda's 250 MiB unpacked limit.
  Source/metadata edits change the ZIP hash/size; artifacts remain private and version-pinned.
- `uv run python -m infra.events.verify`: **passed all three genuine formats** through the deployed
  host API on 8001, actual signed POST on 4567, real S3/SQS/Lambda and persisted internal facts.
  Its first invocation exposed Windows cp1252 console handling of arrows in its success message;
  output was made ASCII and the complete verifier passed. Verification jobs/objects are retained.
- Repeated **real development bootstrap** passed. A privileged before/after comparison verified
  all existing event-development job items and quarantine object-version IDs remained identical.
  Disposable-resource tests additionally verified unrelated notification and queue-policy entries.
- Original separate compatibility suite: **5 passed in 96.08 s**, no skips/xfails. Cold/warm runtime,
  private exact-version SDK access, partial batch retry and both original DLQ gates remain intact.
- Final normal Docker regression: **262 passed, 14 skipped, 1 xfailed**. Skips are five separate
  compatibility and nine separate event-chain tests. The existing strict SSE-S3 xfail remains;
  no encryption-at-rest verification is claimed.
- Final `uv run pytest`: **220 passed, 57 opt-in skips** on Windows Python 3.14.7. Skips are
  18 existing Floci cases, 25 processing-core Floci cases, five compatibility and nine event gates;
  the Docker/separate suites above executed those opted-in checks.
- `uv sync --locked`, Ruff lint, normal and all-profile overlay Compose validation passed.
  Full repository formatting still flags **11 unchanged baseline files**; no unrelated formatting
  was performed. All **13 new Python files** passed targeted formatting. `git diff --check` passed
  with Windows line-ending conversion warnings only.
- Both existing persistence and upload verification scripts **passed** against normal development,
  including API restart, Floci recreation, legacy jobs and retained object bytes.
- Initial event fixture used the SDK's default presigned POST signature variant; it was corrected
  to explicit SigV4. S3 authentication/private bucket enforcement was never disabled or weakened.
- Read-only inspection found no remaining event-test-namespaced functions, queues, tables,
  buckets or roles. Event-development objects/jobs/artifacts remain retained. Both APIs and normal
  Floci were inspected: only lambda-floci had a socket mount. After verification the processing
  API and privileged emulator were stopped; no Lambda runtime containers remained running.
  Normal API/Floci remain healthy on 8000/4566, with the original persistent volume retained.

### Remaining limits and next phase
The implementation is local-only; real AWS IAM/execution-role delivery/encryption, ARM64/rootless
Docker, GitHub-hosted runners, high load and host-crash durability remain unverified. Format validation
is not malware scanning or a security sandbox. Serialized control-plane reconciliation is required
because S3 notification merging has no cross-writer compare-and-swap. Large/slow nested messages can
exhaust bounded retries and require retained-DLQ inspection/redrive. No automatic redriver or sweeper.

Phase 4 is ready to wrap the repeatable unit/regression/compatibility/event commands in GitHub Actions:
all local gates, including final crash/timeout recovery, are green. A GitHub-hosted Linux runner still
needs its own real execution; no CI workflow has been introduced or claimed as passed in this phase.
See ADR 0004 and infra/events/README.md for exact commands, security boundaries and retry semantics.

## Milestone 4 Phase 2 — shared document processing core

Implemented without production notifications, SQS consumers, business Lambda handlers, GitHub
Actions, OCR, text extraction, AI classification or cross-document deduplication. Phase 1 probe
files, API endpoints/schemas, filename alias and JobRepository.save/get signatures are unchanged.
The working tree was clean at the start; no commit/push or Docker volume deletion was performed.

### Files and responsibilities
- `documents/application/processing_service.py`: single transport-independent processing use case;
  checks saved references, claims, stages/hashes bounded bytes, invokes validation, fences results.
- `application/processing_ports.py`, `processing_errors.py`: narrow state/reader/validator contracts,
  retryable infrastructure/claim errors, invalid-event errors and permanent document codes.
- `domain/processing.py`, `domain/models.py`: immutable optional processing facts and declared length.
- `infrastructure/processing_store.py`: conditional DynamoDB claim/recovery/finish UpdateItem calls;
  `processing_mapping.py` and modified `dynamodb_repository.py`: additive internal serialization.
- `infrastructure/s3_object_reader.py`: exact-version GetObject, bounded chunks and body cleanup.
- `infrastructure/document_validator.py`, `validation_worker.py`: bounded child-process format
  validation with maintained Pillow 12.3.0 and pikepdf 10.18.0, without parser diagnostic leakage.
- `bootstrap/processing.py`, `bootstrap/settings.py`: lazy composition and validated processing
  policies. `.env.example` and Compose expose budgets without adding a consumer service.
- `application/upload_service.py`: persists declared upload size internally, retaining HTTP schemas.
- `infra/local/init_s3.py`: enables versioning idempotently without deleting existing objects.
  `infra/iam/processing-policy.json` is a separate undeployed processor permissions example;
  bootstrap IAM example adds PutBucketVersioning, API permissions remain unchanged.
- `tests/unit/test_processing_*.py`, `test_document_validation.py`,
  `tests/integration/test_processing_floci.py`: 103 new cases; `tests/conftest.py` generates genuine
  PDF/PNG/JPEG fixtures. Existing upload-fixture cleanup and bootstrap assertions support versioning.
- README, CHANGELOG and ADR 0003 document connections, policies, invariants and Phase 3 gates.
  `pyproject.toml` / `uv.lock` add the maintained validation dependencies (including transitive lxml).

### Verified behavior and concurrency strategy
- PENDING → PROCESSING → COMPLETED or PROCESSING → FAILED for fixed permanent content codes.
  Internal references, metadata, hash, length and failure details remain absent from public schemas.
- First successful conditional claim selects one exact version. A unique token and normalized UTC
  lease fence every attempt. Only that version may recover after expiry; active conflicts retry.
- Terminal writes require matching token/version, PROCESSING state and a still-valid lease.
  Barrier-coordinated real DynamoDB races demonstrate one initial/recovery winner; explicit clocks
  verify expiry boundaries and stale workers cannot overwrite newer claims or terminal results.
- No processing save/PutItem or HASH# record creation. Actual older versions are read even after
  overwrite, same-version terminal replays are no-ops and other versions cannot replace results.
- Bounded 64 KiB S3 chunks, default 10 MiB staging limit, SHA-256 and declared-size checks; bodies
  close on EOF/early rejection/version mismatch/read error. Temporary files clean up on every exit.
- Genuine valid and invalid PDF/PNG/JPEG cases pass, including truncation, malformed content,
  mismatch, empty/oversized/incorrect-size documents, encrypted PDF and image/PDF resource limits.
- Simulated transient S3 failure against a real selected version leaves PROCESSING, rejects an
  active duplicate, then completes with a fresh token after clock-driven expiry and restored S3.
  Missing exact versions never fall back to latest; infrastructure errors do not become FAILED.
- Existing optional-attribute-free records remain readable; corrupt present new attributes fail
  explicitly. Structured records/key-value processing logs contain only IDs/events/fixed codes.

### Actual verification outcomes
- `uv sync` and `uv sync --locked`: passed; Python >=3.14 and uv_build retained.
- `uv run pytest`: **190 passed, 48 skipped** on Windows Python 3.14.7. Skips are 18 existing
  opt-in Floci cases, 25 new processing Floci cases and five separate Lambda compatibility gates.
- `docker compose --profile test run --build --rm tests`: **232 passed, 5 skipped, 1 xfailed**
  on Linux Python 3.14.10. All 25 processing integration cases passed. Five skipped Lambda gates
  were executed separately; strict SSE-S3 expected failure remains, not resolved encryption proof.
- Separate `compose.lambda.yaml` compatibility run: **5 passed in 77.62 seconds**, no skips/xfails;
  unchanged cold/warm, exact-version S3/DynamoDB, partial batch retry and both DLQ gates passed.
  Probe emulator stopped afterward; no Docker socket added to normal services.
- `uv run ruff check .`: passed. All **23 new/modified Python files** passed targeted formatting.
- Whole-repository format check: **11 existing unchanged files still require formatting**.
  Only files functionally touched by this phase were formatted; no unrelated baseline cleanup.
- Normal and isolated Lambda Compose configurations: passed validation. `git diff --check`: passed
  with Windows line-ending conversion warnings only.
- `uv run python infra/local/verify_persistence.py`: passed API restart/Floci recreation retention.
- `uv run python infra/local/verify_upload.py`: passed host-facing upload, anonymous denial, legacy
  jobs and retained object bytes across Floci recreation. Both scripts retain their development
  verification records/objects and the existing named volume. API and Floci remain running.
- Initial failing runs exposed reserved DynamoDB names (`bucket`, `token`), separate pikepdf
  PasswordError handling, and versioned upload-fixture teardown. All were corrected; final tests
  above have no unexpected failures. The exact disposable bucket/table left by that initial
  teardown were cleaned explicitly, without prefix-wide or development-data deletion.

### Remaining risks and Phase 3 readiness
The shared core is ready for a thin event adapter, **not an already-integrated production workflow**.
Phase 3 still needs S3/SQS event decoding, malformed-message policy, batch acknowledgements,
visibility/lease/receive-count/DLQ alignment and native Linux Lambda packaging/runtime verification.
The existing SDK-only Lambda probe does not establish Pillow/pikepdf wheel compatibility in the
official Lambda image; Linux slim container decoding passes, but that is a different runtime.

Validation is not malware scanning or a security sandbox. Default parser limits are 15 seconds,
20M pixels, 16,384-pixel dimension, 500 PDF pages, 50,000 PDF objects; Linux additionally applies a
512 MiB child address-space cap and ten-second soft CPU budget. Windows has no POSIX memory/CPU
cap. Unexpected native crashes remain retryable. Production memory must cover parent plus child.
Read deadline is cooperative plus SDK timeouts. Workers require synchronized UTC clocks. No lease
heartbeat/sweeper exists; transient failures wait for same-version expiry recovery. A permanently
missing selected version cannot switch to a newer upload and may require operator intervention.
Pre-versioning null objects remain retained but require a fresh upload for processing.

Real AWS IAM/encryption, public API ownership/authentication/quotas, GitHub-hosted runners, hostile
parser fuzzing, production load/crash durability and the final integrated event chain remain
unverified. Existing Phase 1 and Milestone 3 security limitations below still apply. See ADR 0003.

## Milestone 4 Phase 1 — Floci Lambda compatibility gate

Verified locally on Windows Docker Desktop 4.90.0 / Linux-amd64 Docker Engine 29.7.2.
Only compatibility fixtures were added. No `src/`, normal Compose/Dockerfile, API contract,
production ProcessingService, worker fallback, or GitHub Actions implementation was changed.

### Reproduction and scope
```sh
uv sync --locked
docker compose -p eddp-lambda-probe -f compose.lambda.yaml config --quiet
docker compose -p eddp-lambda-probe -f compose.lambda.yaml run --build --rm lambda-tests
docker compose -p eddp-lambda-probe -f compose.lambda.yaml stop lambda-floci
```

The overlay creates its own Floci 2.4.0 instance, network, tmpfs state and test runner. It
publishes no ports and does not mount the development volume. Only the probe emulator gets
the Docker socket; inspection confirmed no socket on the normal API or development Floci.
S3 authentication remained enabled. SDK calls use explicit dummy test/test credentials.
The official Python 3.14 Lambda image is pinned to:
`sha256:cf4c3a72d1cd34b7ae289fef868bac0777afeef9895c5d0a3d83d7dcb4da9a29`.
Docker create events confirmed five runtime containers used this actual image digest.

### Executed compatibility evidence
All five gates passed on three runs. The final run, with five-second function and queue
visibility timeouts and maxReceiveCount=3, completed in **75.33 seconds**:
- `test_python314_cold_and_warm_invocation`: actual Python **3.14**, vendored boto3 **1.43.125**,
  invocation counters **1 then 2**, identical process boot ID across sequential calls.
- `test_post_events_select_exact_versions_readable_from_lambda`: two authenticated presigned
  POSTs to one key created distinct version IDs. ObjectCreated:Post messages supplied matching
  bucket, URL-encoded key, size, sequencer and version ID. Lambda read both exact versions after
  overwrite and wrote matching version IDs, lengths and independently checked digests to its
  disposable DynamoDB table. Anonymous read/write and altered signatures were rejected (403).
- `test_sqs_mapping_partial_failure_retries_only_failed_message`: one actual mixed batch of
  two records; the successful record was delivered **once**, the retry-once record **twice**,
  with ApproximateReceiveCount **2**. The mapping used ReportBatchItemFailures.
- `test_failed_messages_retry_and_reach_dlq[always_fail]`: exactly **three** partial-failure
  deliveries; original message body and ID reached the configured DLQ.
- `test_failed_messages_retry_and_reach_dlq[raise]`: exactly **three** thrown-error deliveries;
  original message body and ID reached the configured DLQ.

S3 notification metadata/read capability and SQS dispatch were tested separately, not installed
as a complete document business workflow. SQS fixtures warm functions before mapping activation;
cold SQS startup visibility behavior is not established by these probes.

### Verification outcomes
- `uv sync`: passed; only dev SDK typing support and marker configuration were extended.
- `uv run pytest`: **112 passed, 23 skipped**. Skips: 18 existing opt-in Floci cases and five
  separately executed Lambda gates. Six new safety/ZIP-packaging unit cases passed.
- `docker compose --profile test run --build --rm tests`: **129 passed, 5 skipped, 1 xfailed**.
  Five skips are the separate Lambda gates; the existing strict SSE-S3 expected failure remains.
- Isolated real Lambda/SQS suite: **5 passed**, no skips or xfails, on each of three runs.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: **failed on 17 pre-existing files**. No unrelated formatting
  was changed. The six new Python files passed a targeted Ruff format check.
- Normal, standalone Lambda, and combined Compose configurations: passed validation.
- `git diff --check`: passed; only Windows line-ending conversion warnings were emitted.
- Resource inspection after the repeated run found no remaining fixture-namespaced functions,
  queues, tables, buckets or roles. Floci's own Lambda staging bucket/log groups were not deleted.
- The probe emulator was stopped after verification to release active socket access. The normal
  development API/Floci remained running; no Docker volume deletion/prune commands were used.
- A Windows import-hook packaging defect discovered by the new unit test was fixed: synthetic
  `six.__path__` must not cause the entire host site-packages directory to be archived. The final
  deterministic ZIP contains only the synthetic handler and selected locked SDK packages.

### Limits and Phase 2 recommendation
The local compatibility gate passes: Lambda is eligible for the next processing-design phase;
there is no evidence requiring an automatic switch to a Docker worker. This is not production
readiness or proof of general reliability under load/crashes/restarts.

No GitHub-hosted Ubuntu runner, ARM64/rootless/remote Docker daemon, real AWS deployment,
execution-role credential delivery, least-privilege IAM enforcement, or encryption at rest was
verified. The function deliberately uses custom PROBE_* dummy credentials, not an execution
role's credentials. Five-second probe visibility meets the function-timeout minimum but is not
the larger AWS-recommended production retry margin. Follow-up work still needs conditional
processing leases, immutable-version job policy, genuine content validation, and a thin handler
around shared application logic. No such business logic or CI/CD workflows were implemented.

See `infra/compatibility/README.md` for exact commands, module responsibilities and security scope.

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
