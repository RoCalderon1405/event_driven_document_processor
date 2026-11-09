# Decision: unprivileged Actions triggers with disposable Docker event gates

## Context

Milestone 4 Phases 1–3 have repeatable offline, Floci and native Lambda event tests, but no hosted
automation. The actual GitHub default branch is master. CI must execute opted-in suites without
silently accepting their default skips, leaking presigned policies, or reusing local durable state.

## Decision

Use SHA-pinned upstream checkout/Python/uv actions on GitHub-hosted Ubuntu 24.04. Ordinary
pull_request and master push triggers use read-only contents permission, credential-free checkout,
no secrets, no shared writable caches and bounded/cancelable jobs. First run locked Python 3.14
quality checks; then build and test isolated Docker stacks. No CD/image publication is introduced.

Keep development Compose files and all processing contracts unchanged. CI overlays require Compose
2.24.4+, remove ports and persistent data mounts, use memory/tmpfs emulator state, and scope projects,
Lambda namespaces and networks to generated names. Validate resolved configuration before startup.
Only the opt-in emulator mounts the Docker socket. This remains daemon-level privilege: disposable
hosted runners are the security boundary, not a claim that untrusted repository code is sandboxed.

The reusable stdlib runner strips ambient application/AWS/Compose configuration and invokes fixed
commands. Its exact-project cleanup never prunes or deletes volumes. A finally block and always
workflow step are best effort under interruption; runner disposal handles hard hosted failures.
Local reproduction must use a trusted checkout/development daemon and preserve cleanup state.
Floci's separate namespaced Lambda code-artifact volumes may remain after successful cleanup;
retain them locally rather than deleting volumes automatically. They do not mount development
data, but repeated local runs consume disk. Hosted runner disposal is responsible for that daemon.

Run regression and the original compatibility/event suites explicitly. A small pytest gate rejects
all Docker skips/new xfails while preserving the one exact known strict SSE assertion xfail.
Unexpected SSE passes remain failures. No content-deduplication, leases or test business logic change.

Publish only numeric test counts and sanitized stage/exit messages, not raw SDK/service/config logs
or traceback artifacts that could contain policies or descriptions. This reduces remote debugging
detail deliberately; maintainers reproduce privately with emulator-only credentials.

Resolve the pre-existing 11-file Ruff baseline as an independently reviewable formatting patch,
including LF checkout policy. Verify AST equivalence and keep it separate from CI and previous
uncommitted Phase 3 changes. Do not weaken full-repository format checks or commit/push automatically.

## Consequences and evidence

Additional Docker startup/native artifact builds and real retry/DLQ waits cost several minutes.
Dependencies and Docker base tags outside the already digest-pinned Lambda runtime still depend on
upstream availability; uv itself and dependency resolution are pinned/locked. Updating action SHAs
requires upstream review. GitHub approval/required-check settings remain manual.

See `infra/ci/README.md` for gates, trust boundaries, reproduction, log tradeoffs and GitHub settings;
`docs/PROJECT_STATUS.md` distinguishes actual local outcomes from a future hosted run. No hosted
success can be claimed for an unpublished working-tree workflow.
