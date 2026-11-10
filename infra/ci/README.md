# GitHub Actions CI and local reproduction

`.github/workflows/ci.yml` runs on ordinary pull requests (including forks), pushes to **master**,
and manual dispatch. The default branch was confirmed with `git ls-remote --symref origin HEAD`;
if GitHub's default branch is renamed, update the push filter too. No paths filter omits tests.

## Gates

- **Frontend quality**: independent Ubuntu 24.04 job with Node.js 24, `npm ci` from
  `frontend/package-lock.json`, ESLint, Prettier, Vitest and the production TypeScript/Vite build.
  Tests run with V8 coverage (`npm run test:coverage`). All commands run in `frontend/`;
  any failure fails the job. No shared npm cache or bundled build artifacts.
- **Python quality**: Ubuntu 24.04, Python 3.14, uv **0.13.6**, `uv sync --locked`, complete offline
  pytest suite with pytest-cov application coverage, `ruff check .`, and `ruff format --check .`.
  Offline emulator-dependent skips are
  intentional; they are executed explicitly in the Docker job, not counted as integration evidence.
- **Docker integration**: starts only after quality passes. Validates both fully resolved Compose
  configurations; builds runtime/API, test, native Lambda, event-test and event-bootstrap targets;
  runs unit/integration tests with Floci, the original five compatibility probes, and all nine real
  S3 → SQS → Lambda tests. Native decoders run in the digest-pinned official Lambda Python 3.14 image.
  This job uses Docker images' pinned uv and lockfile, not host dependency installation.
- **Coveralls reporting**: separate from Docker, waits for Python/frontend quality, downloads their
  seven-day LCOV artifacts and uploads both in one report. Skipped on fork PRs. See
  [coverage scope, authorization and badge verification](../../docs/COVERAGE.md).
- Docker pytest uses `infra.ci.pytest_gate`. **Any skip or new xfail fails the gate**, as do ordinary
  failures, collection errors and empty suites. Only the original strict SSE metadata assertion
  xfail is permitted by exact node ID. Its marker is unchanged: an unexpected pass fails too.
  No `continue-on-error`, marker weakening, retries that swallow failures or broad xfail allowance.
- Frontend/Python/Docker job timeouts are 10/10/35 minutes; backend execution steps are bounded at
  8/30 minutes. Subcommands have shorter bounds (event suite: 15 minutes).
  Real visibility/lease/DLQ tests intentionally take
  several minutes. Concurrency cancellation supersedes older runs for the same PR/ref.

## Security and isolation

All actions are pinned to verified immutable upstream commits (checkout v6, setup-python v6,
setup-uv v7, setup-node v6, upload-artifact v7, download-artifact v8 and Coveralls v2).
No `pull_request_target`, privileged follow-up workflow, untrusted
expression in a shell,
secrets, OIDC, package writes, deployment, image push, or shared writable dependency/build cache.
`contents: read` is the only token permission; checkout does not persist credentials. uv action
caching is disabled. Docker layers stay on the disposable runner; nothing is exported to a cache.

The Lambda emulator has **Docker-daemon-level privilege**, even without `privileged: true`.
Use disposable GitHub-hosted Ubuntu runners, **never persistent/self-hosted runners** with valuable
data or credentials. Fork approval and workflow review remain important: repository code can control
the daemon and cannot be sandboxed by this Python helper. No production credential is needed.
Only lambda-floci mounts the socket; API, bootstrap and tests never receive it. Local reproduction
requires a trusted checkout and a local development daemon, not a production/shared Docker context.

`run.py` generates two unique `eddp-ci-<random>-regression/events` projects. It allowlists only OS and
Docker connectivity environment variables, supplies dummy AWS credentials, disables host AWS config
and ambient uv config, ignores developer `.env` files with an explicit empty env file, and uses fixed
Compose files. CI overrides remove **all published ports and persistent data mounts**, use memory/
tmpfs emulator state, and scope runtime network/namespace/container prefixes to this run. The runner
rejects unsafe resolved configurations before starting services. No development project/image name,
fixed container name, external network or development volume is reused.

Cleanup runs in `finally` and an `always()` workflow step. It accepts only the exact generated pair
in `.ci-state.json`, runs project-scoped `down --remove-orphans`, and never removes volumes, images,
or unrelated Docker resources. It does not prune Docker. SIGKILL/daemon loss can prevent cleanup;
the disposable hosted runner is then discarded. Locally, keep the state file and retry scoped cleanup.
Do not delete it just to bypass a failed cleanup. Concurrent local invocations in one checkout are
refused; separate checkouts can run independently. Compose creates no persistent emulator-data
volume; unused data-volume declarations in the base files are never mounted by this runner.
Floci 2.4.0's Lambda launcher separately creates namespaced **code-artifact volumes** on the daemon
and can retain them after function/stack cleanup (eight in the verified full local run). These are
not development data volumes and are never shared with another namespace. They are deliberately
retained locally under the no-volume-deletion policy; repeated runs consume disk. Inspect them by
their exact `floci_namespace` label if needed. Hosted runner disposal removes the whole ephemeral
daemon; this runner never performs broad pruning or volume deletion to hide that emulator behavior.

### Log policy

The frontend job prints ordinary npm/tool output for this repository's offline unit tests; it
receives no application/registry credentials or real documents. Only LCOV coverage is retained as
a short-lived artifact; Coveralls also reads referenced source files for reporting. npm audit
notices do not fail `npm ci`; dependency vulnerability remediation is a separate reviewed change.

Build/test/Compose output goes to a temporary private file and is deleted after each command.
The backend runner prints only fixed stage names, numeric `CI_RESULT` counters and sanitized
exit/timeout errors. No raw Compose config, Docker/service logs, JUnit traceback artifacts, environment dump,
request bodies, document metadata, presigned URLs/policies or SDK exception messages are published.
This intentionally sacrifices inline traceback detail. To diagnose a failing gate, rerun the matching
suite locally using the project instructions, with dummy emulator credentials only; keep raw output
private and inspect/redact it before sharing. The full test failure still fails CI.

## Reproduce

Prerequisites: Python 3.14, uv 0.13.6, Docker Linux/amd64 containers, network access to dependencies/
images, and **Docker Compose >= 2.24.4** (`!override`/`!reset` support). Windows Docker Desktop Linux
containers are supported for local reproduction; they do not substitute for a hosted Ubuntu run.
Run from the repository root:

```sh
uv sync --locked
uv run python infra/ci/run.py quality
uv run python infra/ci/run.py docker
# Safe to repeat; also use after interrupted/failed cleanup:
uv run python infra/ci/run.py cleanup
```

Frontend reproduction (Node.js 24, from `frontend/`):

```sh
npm ci
npm run lint
npm run format:check
npm run test:coverage
npm run build
```

No local API/gateway ports need to be free, and local development services/data can stay intact.
Docker configuration validation happens before any startup. Existing development persistence
verification remains separate: `uv run python infra/local/verify_persistence.py` retains its data.
Detailed opt-in diagnostic commands remain in `infra/events/README.md` and
`infra/compatibility/README.md`; normal regression is `docker compose --profile test run --build --rm tests`.
Do not add the developer persistence/restart verifier to ephemeral-memory CI and claim durable storage.

For local workflow syntax validation, use Actionlint **1.7.12** from its official release, verifying
the published SHA-256 before execution, then run `actionlint .github/workflows/ci.yml`. Action SHA
updates should be reviewed against upstream source/action.yml and validated again; never replace
the commit pins with floating tags. Actionlint validation is not a hosted workflow execution.

## Manual GitHub settings

1. Enable Actions and permit the pinned upstream actions in organization/
   repository policy. Keep default workflow permissions **read-only** and PR approval/write grants off.
2. Require approval for fork workflows, preferably all outside collaborators. Never provide secrets
   to untrusted PR code. Do not switch this job to a self-hosted runner to avoid hosted limits.
3. After publication and the first successful hosted run, protect `master` with required checks
   **Frontend quality**, **Python quality** and **Docker integration**, pull-request review and
   up-to-date checks as desired.
   Confirm the actual check names in GitHub before saving the rule. Review workflow changes carefully.
4. No AWS/GHCR token, environment, repository secret or deployment configuration.
   Coveralls requires repository authorization as documented in the coverage guide, not a PAT.
   The workflow does not currently enable merge queues; add a reviewed `merge_group` trigger before
   enabling a queue with required checks.

Nothing is committed/pushed automatically. The new workflow cannot run on GitHub until the user
publishes it. Current local versus hosted evidence is recorded in `docs/PROJECT_STATUS.md`.

## Local images only

GHCR publishing automation and its dedicated tooling have been removed. CI does not publish images
or run on release tags. Local Docker runtime builds and Lambda artifact packaging/deployment remain
unchanged; see `infra/events/README.md` for the local event stack.
