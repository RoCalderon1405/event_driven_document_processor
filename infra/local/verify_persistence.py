"""Run an HTTP smoke test across API restart and Floci recreation; retain all data."""

import json
import os
import subprocess
import sys
import time
from http.client import HTTPException
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = f"http://127.0.0.1:{int(os.getenv('API_PORT', '8000'))}"


def compose(*args: str) -> None:
    """Execute Compose from the repository root and fail on unsuccessful commands."""
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, timeout=600)


def request(path: str, payload: dict[str, str] | None = None) -> dict:
    """Send a local HTTP request and decode the API response."""
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(BASE_URL + path, data=body, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=5) as response:
        return json.load(response)


def wait_for_api() -> None:
    """Allow the restarted API a bounded interval to become available."""
    for _ in range(60):
        try:
            request("/health")
            return
        except OSError, HTTPException:
            time.sleep(1)
    raise RuntimeError("API did not become healthy")


def main() -> None:
    """Leave the stack and one verification job intact; never remove volumes."""
    compose("up", "-d", "--build", "--wait", "api")
    job = request(
        "/api/v1/documents",
        {
            "filename": "persistence-check.pdf",
            "content_type": "application/pdf",
        },
    )
    path = f"/api/v1/documents/{job['job_id']}"
    compose("restart", "api")
    wait_for_api()
    if request(path) != job:
        raise RuntimeError("Job changed or disappeared after API restart")
    compose("up", "-d", "--no-deps", "--force-recreate", "--wait", "floci")
    # Run provisioning again to verify that it does not erase existing jobs.
    compose("run", "--rm", "dynamodb-bootstrap")
    if request(path) != job:
        raise RuntimeError("Job changed or disappeared after Floci recreation")
    print("PASS: job persisted across API restart and Floci container recreation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.SubprocessError, URLError, RuntimeError) as error:
        print(f"Persistence verification failed: {type(error).__name__}", file=sys.stderr)
        sys.exit(1)
