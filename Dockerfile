FROM ghcr.io/astral-sh/uv:0.13.6 AS uv
FROM python:3.14-slim AS runtime

COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY infra ./infra
RUN uv sync --frozen --no-dev --no-editable && chown -R app:app /app

USER app
EXPOSE 8000
CMD ["uvicorn", "event_driven_document_processor.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
RUN uv sync --frozen
COPY --chown=app:app tests ./tests
# Workflow contract tests need the CI definition, not any publishing/runtime configuration.
COPY --chown=app:app .github/workflows/ci.yml ./.github/workflows/ci.yml
CMD ["uv", "run", "--no-sync", "pytest"]

# Native wheels are resolved/installed in the pinned Lambda AL2023 runtime, not host Python.
FROM public.ecr.aws/lambda/python:3.14@sha256:cf4c3a72d1cd34b7ae289fef868bac0777afeef9895c5d0a3d83d7dcb4da9a29 AS lambda-package
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /build
COPY pyproject.toml uv.lock README.md ./
RUN uv export --locked --no-dev --no-emit-project -o requirements.txt >/dev/null && \
    uv pip install --python /var/lang/bin/python3.14 --target /asset -r requirements.txt
COPY src/event_driven_document_processor /asset/event_driven_document_processor
COPY infra/events/package.py /build/package.py
RUN python /build/package.py /asset /build/processing.zip

FROM test AS event-test
COPY --from=lambda-package --chown=app:app /build/processing.zip /app/artifacts/processing.zip

FROM runtime AS event-bootstrap
COPY --from=lambda-package --chown=app:app /build/processing.zip /app/artifacts/processing.zip
CMD ["python", "-m", "infra.events.bootstrap"]
