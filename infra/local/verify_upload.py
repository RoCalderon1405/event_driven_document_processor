"""Host-side API/S3 smoke test, including retained objects after Floci recreation."""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import boto3
import httpx
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = f"http://127.0.0.1:{int(os.getenv('API_PORT', '8000'))}"


def compose(*args: str) -> None:
    """Operate only this project's stack and retain its persistent volume."""
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, timeout=600)


def main() -> None:
    """Upload to the untouched API-issued localhost URL, then verify bytes and job state."""
    compose("up", "-d", "--build", "--wait", "api")
    with httpx.Client(timeout=20, trust_env=False) as http:
        legacy = http.post(f"{BASE_URL}/api/v1/documents", json={
            "filename": "legacy-check.pdf", "content_type": "application/pdf",
        })
        if legacy.status_code != 201:
            raise RuntimeError("Metadata-only job creation failed")
        legacy_job = legacy.json()
        data = b"%PDF-1.7\nlocal smoke bytes; not a validated PDF\n"
        issued = http.post(f"{BASE_URL}/api/v1/documents/uploads", json={
            "filename": "smoke.pdf",
            "content_type": "application/pdf", "file_size_bytes": len(data),
        })
        if issued.status_code != 201 or issued.headers.get("Cache-Control") != "no-store":
            raise RuntimeError("Upload issuance failed")
        result = issued.json()
        upload, job = result["upload"], result["job"]
        location = urlsplit(upload["url"])
        if location.scheme != "http" or location.netloc != "localhost:4566":
            raise RuntimeError("API did not issue the expected host-facing local S3 URL")
        response = http.post(
            upload["url"], data=upload["fields"],
            files={"file": ("smoke.pdf", data, "application/pdf")},
        )
        if response.status_code != 204:
            raise RuntimeError("API-issued presigned POST was rejected")
        object_url = f"{upload['url']}/{upload['fields']['key']}"
        if http.get(object_url).status_code != 403:
            raise RuntimeError("Anonymous object read was not denied")
        compose("up", "-d", "--no-deps", "--force-recreate", "--wait", "floci")
        compose("run", "--rm", "dynamodb-bootstrap")
        for expected in (legacy_job, job):
            read = http.get(f"{BASE_URL}/api/v1/documents/{expected['job_id']}")
            if read.status_code != 200 or read.json() != expected:
                raise RuntimeError("Job changed after Floci recreation")
        # Separate privileged test inspector; the application signer needs no read permission.
        s3 = boto3.client(
            "s3", endpoint_url="http://localhost:4566",
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
            aws_access_key_id="test", aws_secret_access_key="test",
            config=Config(
                signature_version="s3v4", s3={"addressing_style": "path"},
                connect_timeout=2, read_timeout=3, retries={"total_max_attempts": 3},
            ),
        )
        try:
            stored = s3.get_object(Bucket=location.path.strip("/"), Key=upload["fields"]["key"])
            with stored["Body"] as body:
                if body.read() != data:
                    raise RuntimeError("Object bytes did not survive recreation")
        finally:
            s3.close()
    print("PASS: host-facing signed upload, anonymous denial, legacy jobs, and object persistence")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Do not print exception messages: HTTP/SDK errors may contain signing fields or URLs.
        print(f"Upload verification failed: {type(error).__name__}", file=sys.stderr)
        sys.exit(1)
