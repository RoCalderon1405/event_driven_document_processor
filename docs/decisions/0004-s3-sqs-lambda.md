# Decision: explicit versioned S3 → SQS → thin Lambda integration

## Context

Phase 2 owns processing claims, immutable version selection, hashing, parsing and terminal fencing.
Phase 3 connects that core to actual upload notifications without duplicating business logic or
attaching consumers to the normal regression bucket, whose invalid-byte fixtures must stay isolated.

## Runtime and transport

- `bootstrap/lambda_handler.py:handler` is the Lambda entrypoint. `documents/events/s3_events.py`
  validates SQS body/S3 envelopes, URL-decodes keys exactly once, extracts the job UUID from the
  opaque quarantine path, and retains version IDs unchanged. The existing ProcessingService
  still checks the decoded bucket/key against the saved reference before any claim or object read.
- Only ObjectCreated events for the configured bucket and quarantine prefix are accepted. All
  create kinds are provisioned with `s3:ObjectCreated:*`, including presigned ObjectCreated:Post.
  Matching Amazon S3 test events are safe no-ops. Missing/null versions, malformed/oversized JSON,
  duplicate JSON object keys, invalid escapes, foreign buckets/paths and unsupported events retry
  and eventually redrive rather than silently disappear. No latest-version inference exists.
- SQS messages can contain multiple S3 records. Each nested request delegates to the same core;
  a failure does not prevent trying other decoded requests. A message is acknowledged only when
  all nested requests are safe outcomes. Return only failed **outer SQS message IDs** through
  ReportBatchItemFailures. Missing outer IDs fail the entire invocation, preventing unsafe partial
  acknowledgements. Unknown infrastructure errors are retried without exception/payload logging.
- Permanent invalid documents are acknowledged only after the core conditionally persists FAILED.
  Active claims raise retryable errors, not successful duplicate acknowledgements. Completed same-
  version records and ignored nonselected versions retain Phase 2's first-successful-claim policy.
  A lost completion response is resolved by a subsequent consistent read, never an unconditional save.
- Before starting each nested request, check Lambda remaining time against the configured worst-case
  record budget. Low-budget work stays retryable. Very large/slow nested messages can exhaust redrive
  before every request is processed; the retained DLQ message needs operator investigation/redrive.
  There is no infinite retry loop or acknowledgement of uncompleted selected work.

## Timing and recovery

Pydantic EventSettings is shared by provisioning and runtime. Default Lambda timeout is 150 seconds,
claim lease 180 seconds, SQS visibility 900 seconds, maxReceiveCount 5, batch size 2, batching window 0.
Require record budget < Lambda timeout < lease and visibility >= max(6 × timeout, lease + 5 seconds).
The record budget includes configured read/parser limits, three SDK-bounded repository operations,
standard-retry backoff, one final read-timeout overrun and a one-second margin. S3 reads additionally
retain Phase 2's cooperative deadline/SDK timeouts.
Native parser children still have separate resource limits. Lambda has 1024 MiB RAM and 512 MiB
ephemeral storage; its parent plus parser must fit those budgets.

A crashed/timed-out worker's selected version is recoverable on the first normal redelivery after
lease expiry. Another concurrent delivery during the lease fails rather than acknowledging work.
Tokens and terminal protection remain exclusively in Phase 2. Standard queues are at-least-once;
duplicate early deliveries are still possible, and all workers need synchronized UTC clocks.
Source retention is four days and DLQ retention fourteen days. Poison/foreign messages and permanently
unavailable selected versions redrive; document failure status is reserved for actual content errors.
No lease sweeper, cross-document hash deduplication or automated DLQ replayer is introduced.

## Packaging and local credentials

Docker's `lambda-package` stage runs in the digest-pinned official Python 3.14 Lambda AL2023 image,
on Linux/amd64. Export the existing lockfile with hashes, install runtime dependencies there and
copy the actual application package. Retain native `.so`, wheel library directories and package
metadata in a deterministic ZIP; exclude caches/host bytecode. Enforce the 250 MiB unpacked limit.
The complete locked runtime set is included for reproducibility, including unused API dependencies;
future packaging minimization must preserve tested native wheels and the lockfile as source of truth.

Provision through a version-pinned private S3 ZIP outside quarantine/, avoiding direct-upload size
limits and recursive processing notifications. The SDK-only Phase 1 ZIP builder stays unchanged.
No production diagnostics/backdoor action or fault injection is added to the business handler.
Crash/timeout injection lives only in a different test artifact/handler wrapping the same core.

Normal AWS deployment uses boto3's workload-role chain. Local Floci explicitly sets
`EDDP_LOCAL_EMULATOR=1`; only validated local HTTP endpoints may bootstrap dummy test/test credentials.
Do not send reserved AWS credential variables to Lambda CreateFunction. This local path proves SDK
signatures/connectivity, not AWS execution-role credential delivery or enforcement of IAM examples.

## Provisioning, preservation and privilege

`infra/events/bootstrap.py` is a separately invoked local-only reconciler. It reuses existing
table/bucket provisioning, creates queues/DLQ/role/function/log group/mapping if absent, reconciles
owned configuration, and never deletes/recreates resources. An incompatible architecture or duplicate
mapping is an explicit failure. Merge the owned queue-policy Sid and S3 notification ID while retaining
unrelated queue statements and all unrelated notification kinds/entries. Preserve object versions,
jobs and artifact versions. Serialize control-plane provisioning: S3 notification read/merge/write
has no cross-writer compare-and-swap, and overlapping externally managed filters may fail validation.

The existing explicit `compose.lambda.yaml` hosts this opt-in stack separately from normal Compose.
It now retains emulator data in a **separate named lambda-data volume**, publishes its authenticated
gateway on loopback 4567 and exposes the optional processing API on loopback 8001. Normal API/Floci
remain on 8000/4566 with their original volume and no Docker socket. Only lambda-floci receives the
socket; this is daemon-level privilege and must remain restricted to trusted local development.
No volume deletion/prune is part of provisioning, testing, verification or documented stop commands.

IAM examples separate API upload privileges, job/versioned-object processing plus SQS consumption,
S3-to-SQS source-scoped queue permission, and privileged event provisioning/PassRole. Provisioning
creates the scoped log group before the function; processing has only stream/write access there.
Templates remain undeployed and must be independently validated in AWS. Existing SSE metadata xfail
and public API authentication/ownership/quota limitations remain unchanged.

## Verification and next phase

Keep host tests offline, normal Floci tests separate, original five compatibility gates synthetic,
and real event-chain tests explicitly opted in with unique disposable resources. Exercise actual
API-issued HTTP POST notifications and native decoders in Lambda, version/order/concurrency behavior,
partial batches, active claims, hard worker failures, poison/DLQ delivery and repeated provisioning.
`infra/events/verify.py` exercises the deployed host-facing API and retains verification objects/jobs.
Record actual outcomes, including skipped/blocked checks, in PROJECT_STATUS.md.

Phase 4 can add GitHub Actions around these repeatable checks. No workflow, GHCR publication,
webhook, OCR, AI classification, hash deduplication or real AWS deployment is part of Phase 3.
