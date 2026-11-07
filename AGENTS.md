# Repository guidance

## Architecture
- Source lives in `src/event_driven_document_processor/`; `documents` is the only business module.
- Preserve modular Clean Architecture: API -> application -> domain; infrastructure implements application ports.
- Keep domain and application free of FastAPI, boto3, and storage serialization details.
- Wire concrete dependencies in `bootstrap/`. Keep `JobRepository.save/get` unchanged.
- Preserve existing endpoints, schemas, UUIDs, UTC timestamps, and `file_name` compatibility.
- Retain the in-memory repository for isolated tests. Do not introduce generic repository frameworks.
- Runtime storage uses DynamoDB `pk = JOB#{job_id}`. Reserve `HASH#{sha256}`; no deduplication yet.
- Use Pydantic Settings for environment configuration; boto3 belongs outside application/domain.

## Python standards
- Python 3.14+, uv dependency management, existing `uv_build` backend.
- Use explicit type hints, focused functions, and useful public docstrings.
- Follow Ruff rules in `pyproject.toml`; line length is 100.
- Translate persistence failures at boundaries; never hide them as missing jobs.
- Never log credentials, document descriptions, or request bodies.
- Keep local infrastructure under `infra/`; never commit real credentials.

## Verification workflow
- Run `uv sync`, `uv run pytest`, and `uv run ruff check .`.
- Validate `docker compose config --quiet`.
- With Docker running: `docker compose --profile test run --build --rm tests`.
- Verify restarts with `uv run python infra/local/verify_persistence.py`; it retains local data.
- Record actual outcomes in `docs/PROJECT_STATUS.md`; distinguish passed, skipped, and blocked checks.
- Do not describe planned functionality or unexecuted checks as completed.
- Do not commit or push automatically.
