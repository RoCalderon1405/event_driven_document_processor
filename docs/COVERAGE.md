# Coverage and Coveralls

## What is measured

- Python: the existing complete offline pytest suite with `pytest-cov`, line and branch
  collection across **all `src/` application code**, including files not imported by tests.
  Tests and `infra/` developer tooling are outside that application scope. Only static
  `if TYPE_CHECKING:` blocks are additionally excluded; coverage.py's standard exclusions remain.
- Frontend: the existing Vitest/jsdom suite with the version-matched V8 coverage provider across
  `frontend/src/**/*.{ts,tsx}`, including unimported files. Only test files, `src/test/` setup/helpers
  and declaration files are excluded. App/bootstrap code is included, even when uncovered.
  Type-only source files have no executable lines.
- There is **no invented minimum percentage** and no exclusion of adapters, error handling,
  bootstrap code or otherwise difficult-to-cover application paths to improve the score.

Python coverage is **offline parent-process coverage**, not an aggregate of Docker, native decoder
subprocesses or Lambda executions. Those suites still run separately in the isolated Docker gate.
In particular, `validation_worker.py` remains in the denominator at 0% even though subprocess
validation tests execute it. Do not present those tests as instrumented coverage. The frontend
report is jsdom unit/component coverage, not browser end-to-end coverage.

## Local reproduction

From the repository root:

```sh
uv sync --locked
uv run pytest --cov --cov-report=term-missing --cov-report=lcov:coverage/python.lcov
# Equivalent test collection plus lint/format and locked sync:
uv run python infra/ci/run.py quality
```

From `frontend/` with Node.js 24:

```sh
npm ci
npm run test:coverage
```

Python emits `coverage/python.lcov`. Vitest emits `frontend/coverage/lcov.info` and
`frontend/coverage/coverage-summary.json`; its console includes statements, branches, functions
and lines. Generated reports and `.coverage*` data are ignored by Git and the Docker build context.
Normal `npm test` and Docker test commands remain usable without enabling coverage.

Both LCOV reports use repository-relative source paths (`src/...` and `frontend/src/...`).
Separators follow the host OS; CI generates them on Linux. Do not manually merge counters or average
language percentages. Coveralls combines covered and executable line counts from both reports.
Python's terminal total combines lines and branches when branch measurement is enabled; it is not
the same metric as a Coveralls line percentage.

## CI integration and security

The existing Python/frontend quality jobs collect coverage during their ordinary test runs and
save **only LCOV files** as `coverage-python` and `coverage-frontend` artifacts for seven days.
Missing files fail the artifact step. No raw test logs, HTML reports, request bodies, credentials
or local environment files are uploaded as artifacts.

A separate **Coveralls reporting** job waits for both quality jobs to pass, downloads only this
workflow run's coverage artifacts, and sends both reports in **one upload** using the supported
`coverallsapp/github-action` v2 integration. This needs no parallel-build finalizer or carry-forward
of stale reports. It uses the built-in `${{ github.token }}`, not a stored Coveralls/PAT secret.
Permissions remain `contents: read`; checkout credentials are not persisted. Actions are pinned to
upstream commits; the Coveralls reporter is version-pinned (v0.6.22), with the action's upstream
release-checksum verification. Dependency caches remain disabled.

Fork PRs still generate coverage and run all quality/Docker checks, but the Coveralls job is skipped:
untrusted fork source is not uploaded to the third-party service by this workflow. There is no
`pull_request_target`, privileged cross-run artifact consumer or write-token follow-up. Same-repo
PRs, master pushes and manual runs can report. The Docker job still depends only on Python quality,
not Coveralls; an authorization/service failure in the reporting job does not skip Docker tests.
Upload failures fail the reporting job rather than silently claiming success.

**Data sharing:** Coveralls' reporter reads the source files referenced by LCOV and sends source and
coverage to Coveralls. Repository authorization must approve that data sharing, especially for
private repositories. Coverage artifacts alone do not contain the full source files, but include
repository filenames, function names and counters. Do not enable debug payload logging in CI.

## Manual activation and verification

1. A repository administrator signs into Coveralls with GitHub and authorizes the repository and,
   where applicable, organization/SSO access or the Coveralls GitHub App. Confirm private-repository
   access and plan availability. The action can create the Coveralls repository on first upload;
   confirm it is visible/enabled in the Coveralls dashboard.
2. Permit the pinned Coveralls/artifact actions under GitHub organization/repository Actions policy.
   Keep workflow permissions read-only; do not add a PAT, package-write grant or production secret.
   Configure desired PR checks/comments through Coveralls' authorized GitHub integration, not a
   broader workflow token. If upload authorization fails, inspect access before changing permissions.
3. Publish the workflow through the normal review process and run it on master or an authorized
   same-repository PR. This task does **not** commit, push, enable apps or change branch protection.
4. Verify **both** artifacts exist, **Coveralls reporting** succeeds, the correct commit/branch is
   shown, both `src/` and `frontend/src/` files appear, zero-hit files remain and line counts match.
   Forks intentionally skip reporting. Review any Coveralls default coverage-drop/status rules;
   this project does not establish or imply a new numeric threshold.
5. Only after a successful hosted upload and correct combined master report, copy the repository's
   dynamic coverage badge/link from Coveralls into README. **No badge is added before that proof.**

Local tests and a checksum-verified reporter `--dry-run` validate collection/parsing/path resolution,
not GitHub authorization, artifact transport, remote upload or hosted checks. Actual results and
remaining limitations are recorded in [project status](PROJECT_STATUS.md).
