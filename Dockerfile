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
CMD ["uv", "run", "--no-sync", "pytest"]
