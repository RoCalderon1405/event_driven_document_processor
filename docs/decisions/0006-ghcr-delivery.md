# Decision: validated, tag-driven delivery of the production API container

## Context

The isolated CI gates validate Python 3.14 application behavior and the real local event chain.
Delivery should publish a versioned runtime image without giving the privileged emulator package
credentials, duplicating CI logic, deploying AWS resources or weakening existing SSE/result gates.

## Decision

Add `workflow_call` to the existing CI and invoke it from a canonical SemVer tag-push release workflow.
Validate that the exact tagged commit belongs to master history, then run the same complete read-only
CI at that revision. Only after success may a separate fresh runner build the explicit `runtime`
Docker target, inspect production invariants and obtain a GITHUB_TOKEN with `packages: write`.
No contents writes, PAT, AWS credentials, cloud deployment or GitHub Release object are required.

Publish the canonical version and full commit-SHA tag in the lowercased repository GHCR namespace.
Do not publish floating aliases. Check the remote Git tag again before publication; handle annotated
tags explicitly. Refuse either existing image tag, including reruns, and serialize publishers for the
whole repository. Fail closed on registry access/transport errors. Keep registry credentials out of
Docker build and store temporary login configuration outside the workspace. Pin upstream Actions
to the existing verified SHAs; the local reusable CI resolves from the same immutable event commit.

Push the commit tag before the version tag and verify both remote manifests against the matching
push digests. Record the resulting content-addressed reference in the workflow job summary. This
delivers the API image only, not a standalone Lambda deployment or a claim of production readiness.

## Boundaries and consequences

GHCR tags are mutable and multi-tag publication is not transactional. "Immutable SHA tag" means a
workflow policy enforced by duplicate checks plus repository-wide serialization, with tag rulesets
and restricted package writers required administratively. Another writer can otherwise race the
workflow. The digest, not a tag, is the intrinsic content identity. Partial publication fails without
rollback or an overwrite-on-retry path; operators inspect it and use a new commit/version if needed.

Only canonical `vMAJOR.MINOR.PATCH[-prerelease]` versions are supported. SemVer build metadata is
rejected because Docker tags cannot contain `+`. One release per commit avoids changing the meaning
of the full-SHA tag. Release version lives in OCI metadata/tags; no package-version edits are automatic.
Architecture is Linux/amd64. Existing floating base-image policy does not promise reproducible bytes.

Read-only CI retains its ordinary PR/master/manual behavior; release and CI concurrency groups are
different to avoid reusable-workflow self-cancellation. Release concurrency does not cancel an active
publisher, but GitHub may supersede pending runs: release tags must be pushed one at a time.

Local policy tests and image smoke checks are not hosted delivery evidence. Registry authentication,
package access and actual push/digest verification require the user to publish a valid tag. See
`infra/release/README.md` for procedure, manual settings, partial-failure handling and trust boundaries;
`docs/PROJECT_STATUS.md` records actual outcomes. Never commit or push automatically.
