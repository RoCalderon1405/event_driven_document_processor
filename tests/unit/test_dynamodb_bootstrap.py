"""Provisioning is idempotent and refuses incompatible existing schemas."""

import runpy
from pathlib import Path
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError, WaiterError

ensure_table = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "infra/local/init_dynamodb.py")
)["ensure_table"]


def table_description(key: str = "pk", kind: str = "S") -> dict:
    return {
        "Table": {
            "KeySchema": [{"AttributeName": key, "KeyType": "HASH"}],
            "AttributeDefinitions": [{"AttributeName": key, "AttributeType": kind}],
        }
    }


def test_existing_table_is_not_recreated() -> None:
    client = Mock()
    client.describe_table.return_value = table_description()
    ensure_table(client, "jobs")
    client.create_table.assert_not_called()
    client.get_waiter.return_value.wait.assert_called_once_with(
        TableName="jobs", WaiterConfig={"Delay": 1, "MaxAttempts": 30}
    )


@pytest.mark.parametrize("race", [False, True])
def test_absent_table_created_or_competing_creator_tolerated(race: bool) -> None:
    client = Mock()
    client.describe_table.side_effect = [
        ClientError({"Error": {"Code": "ResourceNotFoundException"}}, "DescribeTable"),
        table_description(),
    ]
    if race:
        client.create_table.side_effect = ClientError(
            {"Error": {"Code": "ResourceInUseException"}}, "CreateTable"
        )
    ensure_table(client, "jobs")
    client.create_table.assert_called_once_with(
        TableName="jobs",
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.mark.parametrize("key,kind", [("job_id", "S"), ("pk", "N")])
def test_incompatible_schema_fails(key: str, kind: str) -> None:
    client = Mock()
    client.describe_table.return_value = table_description(key, kind)
    with pytest.raises(ValueError):
        ensure_table(client, "jobs")


def test_permission_failure_is_not_treated_as_absence() -> None:
    client = Mock()
    client.describe_table.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException"}}, "DescribeTable"
    )
    with pytest.raises(ClientError):
        ensure_table(client, "jobs")
    client.create_table.assert_not_called()


def test_sort_key_is_rejected() -> None:
    client = Mock()
    description = table_description()
    description["Table"]["KeySchema"].append({"AttributeName": "sk", "KeyType": "RANGE"})
    client.describe_table.return_value = description
    with pytest.raises(ValueError, match="pk HASH key"):
        ensure_table(client, "jobs")


def test_waiter_failure_propagates() -> None:
    client = Mock()
    client.describe_table.return_value = table_description()
    client.get_waiter.return_value.wait.side_effect = WaiterError(
        name="TableExists", reason="Max attempts exceeded", last_response={}
    )
    with pytest.raises(WaiterError):
        ensure_table(client, "jobs")
