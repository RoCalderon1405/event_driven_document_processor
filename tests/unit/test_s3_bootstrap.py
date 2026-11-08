"""Local bucket provisioning must be private, repeatable, and non-destructive."""

import runpy
from pathlib import Path
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

ensure_bucket = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "infra/local/init_s3.py")
)["ensure_bucket"]


def existing_client() -> Mock:
    client = Mock()
    client.get_bucket_location.return_value = {"LocationConstraint": None}
    return client


def test_existing_bucket_is_not_recreated_and_privacy_applied() -> None:
    client = existing_client()
    ensure_bucket(client, "test-uploads", "us-east-1")
    client.create_bucket.assert_not_called()
    client.put_public_access_block.assert_called_once_with(
        Bucket="test-uploads", PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
        },
    )
    client.put_bucket_ownership_controls.assert_called_once_with(
        Bucket="test-uploads",
        OwnershipControls={"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
    )
    client.delete_bucket_policy.assert_called_once_with(Bucket="test-uploads")
    client.delete_bucket_cors.assert_called_once_with(Bucket="test-uploads")
    client.delete_object.assert_not_called()


@pytest.mark.parametrize("region", ["us-east-1", "eu-west-1"])
def test_creation_region_rules(region: str) -> None:
    client = existing_client()
    client.head_bucket.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadBucket")
    client.get_bucket_location.return_value = {
        "LocationConstraint": None if region == "us-east-1" else region,
    }
    ensure_bucket(client, "test-uploads", region)
    expected = {"Bucket": "test-uploads"}
    if region != "us-east-1":
        expected["CreateBucketConfiguration"] = {"LocationConstraint": region}
    client.create_bucket.assert_called_once_with(**expected)


def test_access_denied_is_not_absence() -> None:
    client = existing_client()
    client.head_bucket.side_effect = ClientError({"Error": {"Code": "403"}}, "HeadBucket")
    with pytest.raises(ClientError):
        ensure_bucket(client, "test-uploads", "us-east-1")
    client.create_bucket.assert_not_called()


def test_explicit_cors_only() -> None:
    client = existing_client()
    ensure_bucket(client, "test-uploads", "us-east-1", ("http://localhost:3000",))
    rule = client.put_bucket_cors.call_args.kwargs["CORSConfiguration"]["CORSRules"][0]
    assert rule["AllowedOrigins"] == ["http://localhost:3000"]
    assert rule["AllowedMethods"] == ["POST"]
