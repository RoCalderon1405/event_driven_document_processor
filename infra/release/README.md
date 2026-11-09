# GHCR release process

`.github/workflows/release.yml` publishes the **production API image**, not the Lambda ZIP or a
test image. It does not deploy anything, configure AWS, or make the application production-ready.
Authentication/ownership controls and real AWS validation are still separate work.

## Release contract

- Trigger: a pushed canonical `vMAJOR.MINOR.PATCH` tag, optionally with a SemVer prerelease suffix
  such as `v0.2.0-rc.1`. The broad `v*` trigger is validated before CI; malformed/leading-zero versions
  fail. `+build` metadata is rejected because `+` cannot be represented in Docker tags.
- The exact event commit must match the checkout and peeled Git tag, have a clean checkout, and
  belong to `origin/master` history. Both lightweight and annotated tags are supported. Tag pushes
  from feature branches that are not in master history cannot release.
- The existing CI workflow is called at the **same tagged revision** through `workflow_call`.
  Locked Python quality, lint/format, Docker builds, Floci regression, compatibility and real event
  tests must all succeed. This is a fresh validation, not a lookup of an old branch's green badge.
  No secrets or package-write permissions are passed to these jobs.
- A fresh publishing runner builds `Dockerfile --target runtime --platform linux/amd64`, labels it
  with source/version/full commit, and checks its non-root `app` user, Uvicorn command, application
  import and absence of pytest/Ruff. No Docker socket is mounted in the published image.
- Immediately before publication, the GitHub API checks that the remote tag still resolves to the
  validated commit (including annotated tag peeling). GHCR checks both proposed tags for duplicates.
- Only the publishing job has `contents: read` + `packages: write`. It uses the job's **GITHUB_TOKEN**;
  no PAT, AWS secret, OIDC, registry password secret, or contents-write permission is needed. Checkout
  never persists credentials. Existing checkout/setup-python/setup-uv action SHA pins are reused;
  publication uses the runner's Docker CLI, not additional floating third-party actions.

For this repository, the image is:

```text
ghcr.io/rocalderon1405/event_driven_document_processor:v0.1.0
ghcr.io/rocalderon1405/event_driven_document_processor:sha-<full-40-character-commit>
ghcr.io/rocalderon1405/event_driven_document_processor@sha256:<registry-digest>
```

The repository-derived GHCR path is lowercased. Version tags retain `v`. No moving `latest`, major,
minor or short-SHA aliases are published. The release version is carried by the image tag/OCI label;
this workflow does not automatically edit the Python package version or create a GitHub Release.

The commit tag is pushed first, the version tag last. Both pushes must report the same digest,
and authenticated registry reads must independently confirm it. The workflow's **Publish runtime
image** job summary records both tags and the digest-pinned pull reference. Save that digest with
release records; use it, rather than a mutable tag, when consuming a specific artifact.

## Duplicate and overwrite protection

An existing **version OR commit tag** fails publication, even if it would point to identical bytes.
This makes reruns non-publishing and allows only one release version per commit. Choose a new
commit/version for a subsequent release. Authorization errors, rate limits, timeouts and malformed
registry responses fail closed; only an authenticated manifest `404` means absence.

One repository-wide concurrency group serializes this workflow's publishers, without canceling an
active push. GitHub concurrency retains only one pending run: if many release tags are pushed together,
older pending runs can be replaced. Push one release tag at a time and wait for its result; explicitly
rerun a canceled run after the active release finishes if it has not published any tag.

**GHCR itself does not provide a create-only tag transaction here.** SHA tags are immutable by this
workflow's refusal-to-overwrite policy, not an intrinsic GHCR guarantee. Restrict other writers and
protect Git tags; another independent writer can otherwise race or overwrite tags. Digest references
are the content-addressed identity. Pre/post checks and serialization cannot replace access control.

Two tag pushes are not atomic. If the job fails after the first push (or after both pushes but before
the summary), a later rerun deliberately refuses the existing tag. Inspect the package and compare
digests/revision labels privately; do not delete/force-push Git tags or bypass the checks to retry.
Record an already-complete artifact after manual verification, or release a new commit/version.
No automated rollback, package deletion or partial-release repair is performed.

## One-time GitHub settings

1. Publish these workflow/helper changes to master through review. Permit the pinned upstream actions
   and reusable workflow; keep default workflow permissions read-only. Organization policy must allow
   this publishing job to request `packages: write` and create packages in the owner namespace.
2. Add a tag ruleset for **`v*`**: restrict creation to trusted release maintainers, disallow tag updates
   and deletion, and tightly restrict bypass actors. Protect master and require CI/review. Tag names
   alone are not a security boundary: a tag workflow executes repository code from that commit.
3. If the GHCR package already exists, connect it to this repository and grant this repository
   **Actions write access** in the package's settings. Private/inaccessible packages or missing access
   must fail validation; do not reinterpret a 401/403 as a missing tag.
4. Decide package visibility explicitly in GitHub. The workflow does **not** make packages public or
   change existing visibility. Private consumers need their own read access; do not embed credentials
   in an image or a pull command shared publicly.
5. Review the first hosted release job summary and package tags/digest before claiming delivery works.
   Consider an approval gate as organizational policy; no deployment environment or AWS is configured
   by this implementation.

## Cut a release (user-operated)

After merging the implementation and ensuring the desired commit is on master, run these commands
yourself; the coding agent does not commit, create tags or push automatically:

```sh
git switch master
git pull --ff-only
uv sync --locked
uv run python infra/ci/run.py quality
uv run python infra/ci/run.py docker
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin refs/tags/v0.1.0
```

Choose an unused canonical version; never move an existing tag. Observe **Release** in GitHub Actions.
After success, copy the actual digest-pinned reference from the summary:

```sh
docker pull ghcr.io/rocalderon1405/event_driven_document_processor@sha256:<actual-digest>
```

The placeholder above is not a published artifact. No hosted release or usable digest is claimed
until the workflow has actually completed. First publication/authentication behavior must be verified
on GitHub; local mocked registry tests cannot establish package permissions.

## Local checks and limitations

```sh
uv run pytest tests/unit/test_release.py
uv run python infra/ci/run.py quality
uv run python infra/ci/run.py docker
docker build --platform linux/amd64 --target runtime -t eddp-runtime:local .
```

`python -m infra.release.publish check|build|publish` is intended for a clean GitHub tag-push checkout.
It refuses ordinary local/PR contexts; do not supply a registry token just to bypass that check.
Unit tests cover policy/duplicate/error/partial-publication behavior without remote writes. Production
build smoke tests are local, with network-disabled containers. A local Docker image ID is not a GHCR
registry digest, nor evidence of an actual release. Python/uv/Floci base image tags retain the existing
Dockerfile policy; the lockfile pins dependencies, but byte-identical rebuilds are not guaranteed.

All raw build/push output is captured privately; only sanitized stage errors and public artifact
identifiers/digests are logged. The token is sent to Docker login via stdin, never to Docker build
or child environments. Docker auth configuration lives in a temporary directory removed on success
or error; the runner's existing credentials are not changed. No shared writable cache is introduced.

See [CI security](../ci/README.md), [ADR 0006](../../docs/decisions/0006-ghcr-delivery.md) and
[actual verification status](../../docs/PROJECT_STATUS.md).
