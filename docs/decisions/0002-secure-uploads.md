# Decision: private direct uploads with constrained presigned POST policies

## Context
Milestone 2 stores metadata-only pending jobs through a save/get repository Protocol.
Documents now need direct uploads without putting file bytes through FastAPI, changing old
responses, or introducing workers. This decision supersedes ADR 0001's unpublished Floci port
decision only; its DynamoDB and modular architecture decisions remain valid.

## Decision
- Add `POST /api/v1/documents/uploads` as a combined create-and-authorize use case. Preserve
  the existing metadata-only POST and GET contracts. No authorization renewal or attachment
  to old jobs; expiration requires a new upload job. Status remains PENDING.
- Use a narrow `UploadAuthorizer` application Protocol. Explicit adapter inheritance makes
  implementations easy to identify while preserving Python's structural typing.
- Validate metadata, generate authorization locally, save the immutable bucket/key reference
  with the initial job, and only then return authorization. No signing fields are persisted.
  This avoids read-modify-write races through the unconditional repository save contract.
- Use boto3 `generate_presigned_post`, SigV4, and path-style addressing locally. PUT is simpler
  for raw bytes but lacks POST's file-size range policy; binding Content-Length is less portable
  for browser clients. POST supports exact key/MIME and file-size conditions. Exact declared
  byte length is bounded by configuration (10 MiB default); authorization defaults to 300 seconds.
- Keys are `quarantine/{job_id}/{random_id}`, never filenames, client paths, or `${filename}`.
- Keep new object reference attributes optional for legacy rows. Malformed present references
  are corrupt-data errors, not silently ignored. Existing HTTP schemas hide storage metadata.
- Use a dedicated bucket with all Public Access Block flags, BucketOwnerEnforced, no bucket
  policy/ACL grants, and SSE-S3. Bootstrap owns this bucket's security configuration and removes
  stale bucket policies but never deletes objects. Runtime needs PutObject only on quarantine/*.
- Browser CORS defaults to no origins. Explicit configured HTTP(S) origins may POST; no wildcard.
- Internal operations use `http://floci:4566`; API signing uses `http://localhost:4566`. Generate
  with the intended endpoint and never rewrite signed URLs. Container tests sign for floci;
  a host smoke test separately exercises the deployed API's actual localhost authorization.
- Publish Floci's shared gateway only on 127.0.0.1:4566, retain pinned 2.4.0 and the named volume,
  and enable `FLOCI_SERVICES_S3_ENFORCE_AUTH=true`. Use supported dummy test/test credentials.
  Do not turn authentication off to accommodate tests. The gateway also exposes other emulator
  APIs to local processes; this is not S3-only isolation or real cloud IAM verification.
- Return Cache-Control: no-store and hide signing material from repr/logs. Translate SDK errors
  to sanitized application exceptions and 503 responses. Never return authorization on save failure.

## Security limits
Presigned POST is a bearer capability, not a one-use token; it can be replayed to overwrite its
exact object until expiry. Unique keys isolate jobs, not repeated uses of one authorization.
Size policies constrain bytes and MIME conditions constrain metadata, not actual file formats or
malware. Untrusted bytes remain quarantined; future processing must inspect content before use.
No download/confirmation/processing endpoint, scanning, SQS, Lambda, or webhook is added.

Authorization issuance has no authentication, ownership checks, quotas, or rate limits. This
milestone is local-only. All four controls are prerequisites to public deployment. CORS and
private buckets do not compensate for an unauthenticated authorization issuer. Production needs
HTTPS, real least-privilege roles, appropriate lifecycle/retention, and independent AWS security
verification. Unused jobs/objects remain until explicitly cleaned up; no sweeper is introduced.

## Observed pinned-emulator limitation
Floci 2.4.0 accepts and reports the AES256 bucket encryption configuration, but POST-created
objects do not report ServerSideEncryption on reads. A strict expected-failure integration
test retains the AWS expectation; bucket configuration and all upload authorization/security
tests remain active. No signature validation was disabled. Actual at-rest encryption is not
verified locally and must be tested independently in AWS before a production security claim.
