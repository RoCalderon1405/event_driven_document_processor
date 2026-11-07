# Decision: DynamoDB adapter and local provisioning

## Context
The existing documents module exposes `JobRepository.save/get` and creates metadata-only jobs.
In-memory runtime storage cannot share records between processes or survive a restart.

## Decision
- Keep the port, service, domain models, and existing HTTP contracts unchanged.
- Implement boto3 serialization only in the documents infrastructure adapter. Configure a
  shared low-level client in bootstrap, not a shared mutable boto3 resource object.
- Use one on-demand table with string `pk = JOB#{job_id}`; reserve `HASH#{sha256}` without
  implementing hash records, indexes, scans, deduplication, or new business features.
- Preserve unconditional replacement semantics of `save`; use strongly consistent `GetItem`
  to preserve immediate POST/GET behavior across processes.
- Translate SDK failures into storage-independent application exceptions. HTTP handlers
  return sanitized `503` for unavailable storage or `500` for corrupt records. A successful
  read without an item alone produces `404`.
- Use Pydantic Settings for environment validation and boto3's credential provider chain.
  Bound SDK I/O timeouts and total attempts; do not add a second retry mechanism.
- Provision local resources in a one-shot Compose service before API startup. The API itself
  never creates tables, allowing separate least-privilege runtime and provisioning roles.
- Pin Floci 2.4.0 and explicitly enable persistent mode on a named volume. Use its image
  healthcheck; do not mount the Docker socket or publish Floci ports.
- Keep `/health` as the existing liveness endpoint, not a new storage-readiness contract.

## Consequences
Unit/contract tests remain isolated via in-memory storage and SDK stubs. Floci tests require
explicit opt-in and disposable tables. Emulator tests do not prove AWS IAM or crash/power-loss
durability. Runtime has no silent in-memory fallback. A write timeout may be ambiguous, and
POST is still non-idempotent. Concurrent future status updates will need a separate guarded
transition design; that is outside this milestone.
