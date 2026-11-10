<div align="center">

# EventDriven Document Processor

**Direct uploads · Version-pinned processing · Retry-safe events**

A full-stack document processing application built with **Python, FastAPI, React, and AWS-compatible services**.
Upload documents, track their status, and inspect validation results through an event-driven pipeline.

[![CI](https://github.com/RoCalderon1405/event_driven_document_processor/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/RoCalderon1405/event_driven_document_processor/actions/workflows/ci.yml)
[![Coverage Status](https://coveralls.io/repos/github/RoCalderon1405/event_driven_document_processor/badge.svg?branch=master)](https://coveralls.io/github/RoCalderon1405/event_driven_document_processor?branch=master)
[![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-19-149ECA?style=flat-square&logo=react&logoColor=white)](https://react.dev/)
[![Docker](https://img.shields.io/badge/Docker-local--first-2496ED?style=flat-square&logo=docker&logoColor=white)](docs/DEVELOPMENT.md)

[**Quick start**](#quick-start) · [**Architecture**](#architecture) · [**Features**](#key-features) · [**Testing**](#quality--testing) · [**Documentation**](#documentation)

</div>

---

## Overview

**EventDriven Document Processor** is a local-first application for uploading **PDF, PNG, and JPEG** files to private S3-compatible storage and processing them asynchronously through **S3 → SQS → Lambda → DynamoDB**.

Its React interface supports drag-and-drop uploads, progress indicators, job tracking, and processing metadata. The system is implemented and tested locally using **Floci**; it is **not deployed to AWS**.

## Application screenshots

Real Playwright captures of the local application, using a generated test PDF with no personal data.

### Document upload

![Desktop document upload interface with a file dropzone and an empty Recent Documents section](docs/assets/screenshots/document-upload-desktop.png)

### Completed processing

The same test PDF after the real S3 → SQS → Lambda → DynamoDB flow, with its SHA-256,
processed size, timing and validation result.

![Completed PDF with upload confirmation and processing results in Recent Documents](docs/assets/screenshots/document-results-desktop.png)

### Responsive mobile layout

The upload form and completed document at a 390 px viewport; the full SHA-256 wraps within the card.

<img src="docs/assets/screenshots/document-mobile.png" alt="Mobile document upload and completed processing results in a single-column layout" width="320">

## Why this project matters

Uploading a file is straightforward. Correctly handling **duplicate notifications, overwritten objects, retries, and worker failures** is harder.

- **Reliable processing** — conditional claims, leases, and fencing tokens protect results from concurrent and stale workers.
- **Clear architectural boundaries** — FastAPI and Lambda adapters share application use cases without coupling business logic to their transports.
- **Testable behavior** — integration tests exercise actual S3/SQS/Lambda events, content validation, recovery, and dead-letter delivery.

## Tech stack

**Frontend**

![React](https://img.shields.io/badge/React-19-149ECA?style=flat-square&logo=react&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-6-3178C6?style=flat-square&logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-8-646CFF?style=flat-square&logo=vite&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)

**Backend & validation**

![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=flat-square&logo=pydantic&logoColor=white)
![boto3](https://img.shields.io/badge/boto3-AWS_SDK-232F3E?style=flat-square)
![Pillow](https://img.shields.io/badge/Pillow-image_validation-334155?style=flat-square)
![pikepdf](https://img.shields.io/badge/pikepdf-PDF_validation-334155?style=flat-square)

**Event pipeline & local infrastructure**

![S3](https://img.shields.io/badge/S3-private_uploads-3F8624?style=flat-square)
![SQS](https://img.shields.io/badge/SQS-retries_%2B_DLQ-9D277C?style=flat-square)
![Lambda](https://img.shields.io/badge/Lambda-event_workers-FF9900?style=flat-square)
![DynamoDB](https://img.shields.io/badge/DynamoDB-job_state-4053D6?style=flat-square)
![Docker](https://img.shields.io/badge/Docker_Compose-2496ED?style=flat-square&logo=docker&logoColor=white)
![Floci](https://img.shields.io/badge/Floci-2.4.0-334155?style=flat-square)

**Developer experience & quality**

![uv](https://img.shields.io/badge/uv-0.13.6-DE5FE9?style=flat-square&logo=uv&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white)
![Ruff](https://img.shields.io/badge/Ruff-D7FF64?style=flat-square&logo=ruff&logoColor=black)
![Vitest](https://img.shields.io/badge/Vitest-tests-6E9F18?style=flat-square&logo=vitest&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-CI-2088FF?style=flat-square&logo=githubactions&logoColor=white)

## Architecture

```mermaid
flowchart LR
    UI["React + TypeScript"] -->|"Authorize upload / poll status"| API["FastAPI"]
    UI -->|"Presigned POST"| S3[("Private S3")]
    API -->|"Job state"| DB[("DynamoDB")]
    S3 -->|"ObjectCreated"| SQS["SQS + DLQ"]
    SQS --> LAMBDA["Lambda handler"]
    LAMBDA --> CORE["ProcessingService"]
    CORE -->|"Read pinned version"| S3
    CORE -->|"Conditional update"| DB
```

The backend follows **Clean Architecture**: adapters → application → domain, with infrastructure implementing ports and concrete dependencies wired in `bootstrap/`.

See the [architecture decision records](docs/decisions/) for the concurrency, storage, security, and event-processing trade-offs.

## Key features

| Capability | Implementation |
| --- | --- |
| **Direct browser uploads** | Private presigned S3 POST, client-side validation, and progress reporting |
| **Document tracking** | Job status polling, recent documents, and local browser history |
| **Processing results** | SHA-256, processed size, timestamps, duration, and failure codes |
| **Retry-safe execution** | Version-pinned reads, conditional claims, leases, and fencing tokens |
| **Content validation** | PDF/PNG/JPEG content checks; invalid formats end in `FAILED` |
| **Event resilience** | SQS retries, partial batch failures, and a dead-letter queue |
| **Automated checks** | Python and frontend quality gates plus isolated event-chain tests |

> [!IMPORTANT]
> **Local development only.** The API does not yet enforce authentication, document ownership, quotas, or rate limits. Format validation is **not** malware scanning. Do not expose this stack publicly.

## Quick start

**Prerequisites:** Docker Desktop with Linux containers and Docker Compose. To run Python tooling locally, use Python 3.14 and uv 0.13.6. For the frontend, use Node.js 24.

### 1. Start the standard API and storage stack

```bash
docker compose up --build -d --wait api
```

- **Swagger UI:** http://localhost:8000/docs
- **Floci gateway:** http://localhost:4566

The default stack supports document jobs and uploads but **does not consume S3 events**.

### 2. Run the full event-processing stack

```bash
docker compose -p eddp-lambda-probe -f compose.lambda.yaml --profile processing up --build -d processing-api
```

- **Event API:** http://localhost:8001/docs
- **Event Floci gateway:** http://localhost:4567

The event stack is isolated from the standard environment. See the [event-stack guide](infra/events/README.md) for setup, verification, and safe shutdown.

### 3. Start the React frontend

```bash
cd frontend
npm ci
npm run dev
```

Open **http://localhost:5173**. For end-to-end processing, configure Vite's `/api` proxy to target the event API at `http://localhost:8001` and follow the [frontend networking instructions](frontend/README.md).

### Main API endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/documents` | Create a metadata-only job |
| `POST` | `/api/v1/documents/uploads` | Create a job and authorize direct upload |
| `GET` | `/api/v1/documents/{job_id}` | Retrieve status and available processing results |

## Quality & testing

```bash
uv sync --locked
uv run python infra/ci/run.py quality
uv run python infra/ci/run.py docker
```

The quality gates include locked dependencies, Python tests, Ruff, isolated Docker integration, Lambda compatibility, and real event-chain checks. Frontend CI runs locked npm installation, linting, formatting, tests, and a production build.

The [CI workflow](.github/workflows/ci.yml) runs on pull requests and pushes to `master`. See [test evidence](docs/PROJECT_STATUS.md) for verified counts and the documented strict Floci SSE-metadata expected failure; see [coverage details](docs/COVERAGE.md) for Python and TypeScript coverage.

## Documentation

| Guide | Contents |
| --- | --- |
| [Development](docs/DEVELOPMENT.md) | Configuration, API examples, and local workflows |
| [Frontend](frontend/README.md) | React usage, networking/CORS, and component tests |
| [Event stack](infra/events/README.md) | S3/SQS/Lambda setup and verification |
| [CI](infra/ci/README.md) | Isolated gates, security boundaries, and reproducibility |
| [Coverage](docs/COVERAGE.md) | Coverage metrics and Coveralls configuration |
| [Architecture decisions](docs/decisions/) | Key implementation trade-offs |
| [Project status](docs/PROJECT_STATUS.md) · [Changelog](CHANGELOG.md) | Evidence, milestones, and history |

## Future improvements

- Authentication, authorization, ownership controls, rate limiting, and quotas before public use.
- Real AWS IAM, encryption, load, and failure testing.
- Cross-document SHA-256 deduplication (separate from implemented event idempotency).
- Optional webhooks, expanded observability, and DLQ recovery tooling.

---

<div align="center">

**Built to explore reliable, event-driven application design.**

[Back to top](#eventdriven-document-processor)

</div>
