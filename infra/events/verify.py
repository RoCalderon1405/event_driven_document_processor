"""Host-facing HTTP smoke test for the explicit event stack; verification data is retained."""

import hashlib
import io
import time

import boto3
import httpx
import pikepdf
from PIL import Image


def main() -> None:
    """Prove real API-issued POSTs and persisted hashes, without printing bearer policies."""
    documents = {}
    with pikepdf.new() as pdf:
        pdf.add_blank_page()
        buffer = io.BytesIO()
        pdf.save(buffer)
        documents["application/pdf"] = buffer.getvalue()
    for mime, format_name in (("image/png", "PNG"), ("image/jpeg", "JPEG")):
        buffer = io.BytesIO()
        with Image.new("RGB", (8, 8), "blue") as image:
            image.save(buffer, format=format_name)
        documents[mime] = buffer.getvalue()
    ddb = boto3.client(
        "dynamodb",
        endpoint_url="http://localhost:4567",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    try:
        with httpx.Client(timeout=15, trust_env=False) as http:
            for mime, data in documents.items():
                issued = http.post(
                    "http://localhost:8001/api/v1/documents/uploads",
                    json={
                        "filename": "event-verification",
                        "content_type": mime,
                        "file_size_bytes": len(data),
                    },
                )
                issued.raise_for_status()
                result = issued.json()
                authorization = result["upload"]
                # Refuse an unexpected target rather than following a bearer URL off-host.
                if not authorization["url"].startswith("http://localhost:4567/"):
                    raise ValueError("Expected the local event-stack upload endpoint")
                upload = http.post(
                    authorization["url"],
                    data=authorization["fields"],
                    files={"file": ("fixture", data)},
                )
                upload.raise_for_status()
                version_id = upload.headers["x-amz-version-id"]
                job_id = result["job"]["job_id"]
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    response = http.get(f"http://localhost:8001/api/v1/documents/{job_id}")
                    response.raise_for_status()
                    status = response.json()["status"]
                    if status in {"COMPLETED", "FAILED"}:
                        break
                    time.sleep(0.5)
                else:
                    raise TimeoutError("Event-stack job did not finish")
                if status != "COMPLETED":
                    raise AssertionError("Genuine verification document was rejected")
                item = ddb.get_item(
                    TableName="event-document-jobs",
                    Key={"pk": {"S": f"JOB#{job_id}"}},
                    ConsistentRead=True,
                )["Item"]
                facts = item["processing"]["M"]
                assert facts["version_id"]["S"] == version_id
                assert facts["sha256"]["S"] == hashlib.sha256(data).hexdigest()
                print(f"PASS: host API -> POST -> SQS -> native Lambda -> DynamoDB ({mime})")
    finally:
        ddb.close()


if __name__ == "__main__":
    main()
