"""CI isolation, scoped cleanup, redacted diagnostics and strict opt-in result enforcement."""

import json
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from infra.ci import run

# Exercise an independent plugin instance, not the gate enforcing this very test run.
pytest_gate = SimpleNamespace(**runpy.run_path(str(run.ROOT / "infra/ci/pytest_gate.py")))

PREFIX = "eddp-ci-0123456789abcdef"


def test_environment_drops_credentials_and_application_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "AWS_SESSION_TOKEN",
        "COMPOSE_PROJECT_NAME",
        "COMPOSE_FILE",
        "RUN_EVENT_TESTS",
        "DYNAMODB_TABLE_NAME",
        "UV_INDEX_URL",
        "PYTEST_ADDOPTS",
        "PYTHONPATH",
    ):
        monkeypatch.setenv(key, "PRIVATE")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "PRIVATE")
    env = run.clean_environment()
    assert "PRIVATE" not in env.values()
    assert env["AWS_ACCESS_KEY_ID"] == "test"
    assert env["COMPOSE_DISABLE_ENV_FILE"] == "1"


@pytest.mark.parametrize("name", ["development", PREFIX, PREFIX + "-events;echo private", ""])
def test_compose_refuses_non_ci_names(name: str) -> None:
    with pytest.raises(ValueError):
        run.compose(name)


def test_compose_uses_only_fixed_files_and_empty_env() -> None:
    command = run.compose(PREFIX + "-events")
    assert command[command.index("--env-file") + 1] == "infra/ci/empty.env"
    assert "compose.lambda.yaml" in command
    assert "infra/ci/compose.events.yaml" in command


@pytest.mark.parametrize(
    "unsafe",
    [
        {"ports": [{"published": "4566"}]},
        {"container_name": "development"},
        {"volumes": [{"type": "volume", "source": "floci-data", "target": "/app/data"}]},
        {"volumes": [{"type": "bind", "source": "/private", "target": "/private"}]},
        {"privileged": True},
    ],
)
def test_resolved_compose_rejects_development_access(unsafe: dict) -> None:
    config = {"name": PREFIX + "-events", "services": {"api": unsafe}}
    with pytest.raises(ValueError):
        run.validate_config(config, PREFIX + "-events")


def test_resolved_compose_accepts_only_emulator_socket() -> None:
    project = PREFIX + "-events"
    service = {
        "environment": {
            "FLOCI_STORAGE_MODE": "memory",
            "FLOCI_DOCKER_RESOURCE_NAMESPACE": project,
            "FLOCI_SERVICES_LAMBDA_DOCKER_NETWORK": project + "_lambda_probe",
        },
        "volumes": [
            {"type": "bind", "source": "/var/run/docker.sock", "target": "/var/run/docker.sock"}
        ],
    }
    config = {"name": project, "services": {"lambda-floci": service}}
    run.validate_config(config, project)
    service["environment"]["FLOCI_DOCKER_RESOURCE_NAMESPACE"] = "development"
    with pytest.raises(ValueError):
        run.validate_config(config, project)


def test_command_emits_only_numeric_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def execute(args: list[str], **kwargs: Any) -> SimpleNamespace:
        kwargs["stdout"].write(
            b"PRIVATE signed URL body\nCI_RESULT passed=9 failed=0 errors=0 skipped=0 xfailed=0\n"
        )
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(subprocess, "run", execute)
    with pytest.raises(RuntimeError, match="exit 1"):
        run.command(["unused"], "test gate")
    output = capsys.readouterr().out
    assert "PRIVATE" not in output
    assert "CI_RESULT passed=9" in output


def test_cleanup_is_exact_and_retains_state_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = tmp_path / "state.json"
    projects = [PREFIX + "-regression", PREFIX + "-events"]
    state.write_text(json.dumps(projects))
    monkeypatch.setattr(run, "STATE", state)
    execute = Mock(side_effect=[RuntimeError("failed"), ""])
    monkeypatch.setattr(run, "command", execute)
    with pytest.raises(RuntimeError):
        run.cleanup()
    assert state.exists()
    for call, project in zip(execute.call_args_list, reversed(projects), strict=True):
        assert call.args[0] == run.compose(project) + [
            "down",
            "--remove-orphans",
            "--timeout",
            "15",
        ]
        assert "--volumes" not in call.args[0]
    execute.side_effect = None
    run.cleanup()
    assert not state.exists()


def test_cleanup_refuses_arbitrary_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = tmp_path / "state.json"
    state.write_text('["development", "development"]')
    monkeypatch.setattr(run, "STATE", state)
    execute = Mock()
    monkeypatch.setattr(run, "command", execute)
    with pytest.raises(ValueError):
        run.cleanup()
    execute.assert_not_called()


def test_failed_docker_gate_still_cleans_its_projects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = tmp_path / "state.json"
    monkeypatch.setattr(run, "STATE", state)
    monkeypatch.setattr(run, "command", Mock(side_effect=["5.5.1", RuntimeError("build failed")]))
    cleaned = Mock()
    monkeypatch.setattr(run, "cleanup", cleaned)
    with pytest.raises(RuntimeError):
        run.docker_gates()
    cleaned.assert_called_once()
    assert all(run.PROJECT.fullmatch(name) for name in json.loads(state.read_text()))


@pytest.mark.parametrize(
    "skipped,xfail,node,failed,allowed",
    [
        (True, True, pytest_gate.SSE_GAP, False, True),
        (True, False, "test_disabled", False, False),
        (True, True, "new_xfail", False, False),
        (False, True, "unexpected_pass", False, False),
        (False, False, "ordinary_pass", False, True),
        (False, False, "ordinary_failure", True, True),
    ],
)
def test_result_gate_never_hides_skips_or_new_expected_failures(
    skipped: bool,
    xfail: bool,
    node: str,
    failed: bool,
    allowed: bool,
) -> None:
    pytest_gate.pytest_sessionstart(None)
    pytest_gate.counts["passed"] = 1
    report = SimpleNamespace(skipped=skipped, failed=failed, when="call", nodeid=node)
    if xfail:
        report.wasxfail = "reason"
    pytest_gate.pytest_runtest_logreport(report)
    session = SimpleNamespace(exitstatus=1 if failed else 0)
    pytest_gate.pytest_sessionfinish(session, session.exitstatus)
    assert (session.exitstatus == 0) == (allowed and not failed)
    pytest_gate.pytest_sessionstart(None)


@pytest.mark.parametrize(
    "body,code",
    [
        ("def test_case(): assert True", 0),
        ("def test_case(): assert False", 1),
        ("import pytest\n@pytest.mark.skip\ndef test_case(): pass", 1),
        ("import pytest\n@pytest.mark.xfail\ndef test_case(): assert False", 1),
        ("import pytest\n@pytest.mark.xfail\ndef test_case(): assert True", 1),
    ],
)
def test_real_pytest_gate_exit_status(tmp_path: Path, body: str, code: int) -> None:
    """Verify actual pytest hook ordering, not only synthetic report objects."""
    (tmp_path / "test_gate.py").write_text(body)
    env = run.clean_environment() | {"PYTHONPATH": str(run.ROOT)}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "infra.ci.pytest_gate",
            "-q",
            "--tb=no",
            str(tmp_path),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == code
    assert b"CI_RESULT" in result.stdout
