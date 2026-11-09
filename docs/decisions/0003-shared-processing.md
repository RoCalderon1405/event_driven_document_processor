# Decision: version-fenced shared processing, independent of event transport

## Context

Phase 1 established local Floci Python 3.14 Lambda/SDK/SQS compatibility, not business processing
or native decoder packaging. Presigned POSTs remain replayable until expiry; processing must
not accidentally read newer bytes or let a stale worker publish over a newer attempt.
ADR 0001's save/get contract and ADR 0002's public response/security contracts remain intact.

## Decision and module connections

- `documents/application/processing_service.py` owns the sole processing orchestration. It reads
  a snapshot through JobRepository and uses three narrow Protocols in `processing_ports.py`:
  ProcessingStore, ObjectReader and DocumentValidator. No SDK, FastAPI or DynamoDB attribute
  mapping enters the application/domain. No S3/SQS event parsing or batch acknowledgements yet.
- `bootstrap/processing.py` lazily composes DynamoDBJobRepository, DynamoDBProcessingStore,
  S3ObjectReader and IsolatedDocumentValidator using validated plain settings. It does not import
  FastAPI, install notifications, or start a worker. The existing API composition remains separate.
- Domain `ProcessingMetadata` holds the selected version, current attempt token and UTC timestamps,
  then optional completion hash/actual length or fixed FailureCode. DocumentJob adds optional
  declared_size_bytes and processing. Existing explicit API schemas expose none of these fields.
- New uploads persist declared size. Missing optional DynamoDB attributes remain legacy-compatible;
  malformed present values remain PersistenceDataError, not absence. No migration/scan is required.

## Atomic concurrency rules

1. Claim a saved upload reference only with a real non-null version and UUID attempt token.
   Conditional UpdateItem checks bucket/key **again at the write boundary**, not only on the
   application snapshot. Claiming cannot create a missing job.
2. A PENDING record without processing metadata can atomically become PROCESSING, selecting its
   version. First successful claim wins, not earliest upload timestamp or latest S3 version.
3. A PROCESSING record may acquire a new attempt only when its lease is expired (`<= now`) and
   the proposed version equals the already-selected version. Concurrent recovery has one winner.
4. Finish requires PROCESSING, matching token/version and lease strictly `> now`. Replace only
   status and the internal processing map, never the whole job. Expired/stale workers cannot
   publish either COMPLETED or FAILED, including after another worker reaches terminal state.
5. Fixed-width, microsecond UTC timestamp serialization makes lexical DynamoDB lease comparison
   valid. Workers require synchronized clocks. These lease fields are not DynamoDB TTL attributes.
6. No processing operation calls unconditional save/PutItem. Existing save retains replacement
   semantics for compatibility; current creation services use fresh UUIDs only. Do not use save
   as a future processing/update API. No generic repository framework or duplicated worker logic.

Conditional conflicts return False from the adapter and become retryable ProcessingRetryableError
in the use case. A subsequent delivery takes a fresh consistent snapshot. Terminal same-version
replays return ALREADY_TERMINAL; another selected version returns OTHER_VERSION without S3 access.
No cross-document deduplication is implemented: hashes are facts on JOB# items, not HASH# claims.

## Bytes, format policy and resource boundaries

- Reject missing/unversioned events and mismatched saved references before reading object bytes.
  ObjectReader calls GetObject with VersionId and checks the returned version. No latest fallback.
- Stream 64 KiB chunks into an automatically cleaned private temporary directory. Bound staged
  bytes (10 MiB default, configurable up to 100 MiB), hash with hashlib, reject empty/oversized
  streams and compare final length with the declared upload size when available. Legacy rows
  without declared size can still be processed if they have a real versioned object reference.
- SDK stream framing failures are infrastructure failures, not proof of invalid content. Close
  bodies in finally, including early rejection/version mismatch. Local disk errors are retryable.
- Validate actual PDF/PNG/JPEG format with maintained pikepdf/qpdf and Pillow. Disable PDF recovery,
  check page tree and syntax/streams without text extraction. Reject encrypted PDFs, empty page
  trees, malformed/truncated content, mismatched formats, animated images and trailing image data.
  Verify PNG integrity and fully decode images; signatures alone are not sufficient acceptance.
- Default image limits: 20 million pixels and 16,384 pixels per dimension. PDF budgets: 500 pages,
  50,000 objects. Decoder runs in a new process with a 15-second wall deadline; Linux adds 512 MiB
  address-space and ten-second soft CPU limits, core dumps disabled. Parent timeout kills/waits
  for its direct child. Windows has no equivalent POSIX address-space/CPU enforcement here.
- Validation child output is discarded; only fixed exit codes cross the boundary. Unexpected
  native crashes/library startup failures are retryable, not permanent invalid-document evidence.
  Timeout/resource-limit results are permanent policy rejections. Limits are not proof against
  all parser vulnerabilities, nor malware scanning, content sanitization or a security sandbox.

## Failure and delivery semantics

Permanent violations commit PROCESSING → FAILED with only an allowlisted code: EMPTY, TOO_LARGE,
SIZE_MISMATCH, INVALID_FORMAT, FORMAT_MISMATCH or RESOURCE_LIMIT. Successful validation commits
COMPLETED with hash/length. No raw parser exception, filename, description, object key, document
contents, SDK payload or authorization material is logged by processing. Logs carry fixed events,
job IDs and fixed failure codes, including structured LogRecord fields.

S3 errors (including missing versions/AccessDenied), DynamoDB outages, staging failures and active
or lost claims propagate. No terminal failure is written for them. An ambiguous write response
may have committed: retry must re-read rather than undo it. Claims remain recoverable after lease
expiry for the **same version only**; no heartbeat, lease release, polling worker or sweeper exists.
A selected unavailable/deleted version does not switch to newer content and may require operator
intervention after retries. Invalid event/job references raise a distinct error without failing jobs.

## Local provisioning, IAM and Phase 3 gate

Bootstrap enables bucket versioning idempotently and preserves all existing objects/null versions.
Old null-version objects are not silently processed; create a new upload. Disposable upload-test
cleanup now deletes exact versions/delete markers only in the fixture's uniquely created bucket.
S3 authentication/private bucket controls remain enabled; no development notifications are added.
The API IAM example remains narrow. A separate processor example grants only GetItem/UpdateItem
for JOB# keys and GetObjectVersion on quarantine objects. Bootstrap adds PutBucketVersioning.
These are undeployed templates, not evidence of real AWS authorization or encryption at rest.

Phase 3 should add only thin event decoding/batch handling around this core, with URL-decoding,
malformed-event policy, receive-count/DLQ strategy and visibility/lease timing verified together.
An active lease is not an acknowledgeable duplicate; retry windows must outlast recoverable claims
without prematurely exhausting redrive. Choose Lambda memory/ephemeral storage/timeout for the
parent plus decoder budget. The Phase 1 SDK-only ZIP is deliberately not extended into business
packaging: native Pillow/pikepdf wheels must be built for the actual Linux Lambda architecture
and tested in that runtime before declaring the integrated workflow ready.

No GitHub Actions, OCR, text extraction, AI classification, deduplication, production notifications,
SQS consumers, business handler, or real AWS infrastructure is introduced by this decision.
