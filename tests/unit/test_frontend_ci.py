"""Guard the small frontend workflow and its read-only, non-publishing boundary."""

import re
from pathlib import Path
from unittest.mock import Mock

import pytest

from infra.ci import run

ROOT = Path(__file__).resolve().parents[2]


def test_frontend_ci_runs_locked_gates_in_order() -> None:
    """Keep the real workflow commands aligned with local reproduction."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    frontend = workflow.split("  frontend:\n", 1)[1].split("  quality:\n", 1)[0]
    assert "working-directory: frontend" in frontend
    assert "node-version: '24'" in frontend
    assert "package-manager-cache: false" in frontend
    commands = re.findall(r"^        run: (.+)$", frontend, re.MULTILINE)
    assert commands == [
        "npm ci",
        "npm run lint",
        "npm run format:check",
        "npm run test:coverage",
        "npm run build",
    ]
    assert "timeout-minutes: 10" in frontend
    assert "persist-credentials: false" in frontend
    assert "continue-on-error" not in workflow


def test_ci_actions_remain_pinned_and_non_publishing() -> None:
    """All remaining jobs use immutable actions and no registry-write automation."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    actions = re.findall(r"uses: (\S+)", workflow)
    assert actions
    assert all(re.fullmatch(r"[\w/-]+@[0-9a-f]{40}", action) for action in actions)
    assert "  contents: read" in workflow
    for forbidden in ("packages:", "secrets.", "pull_request_target", "workflow_call:"):
        assert forbidden not in workflow
    assert not (ROOT / ".github/workflows/release.yml").exists()
    assert not (ROOT / "infra/release/publish.py").exists()


def test_coveralls_combines_only_current_run_reports_without_blocking_docker() -> None:
    """Publication is read-only, fork-safe and separate from the isolated Docker gate."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    reporting = workflow.split("  coveralls:\n", 1)[1].split("  docker:\n", 1)[0]
    docker = workflow.split("  docker:\n", 1)[1]
    assert "needs: [quality, frontend]" in reporting
    assert "github.event.pull_request.head.repo.full_name == github.repository" in reporting
    assert "files: coverage/python.lcov coverage/lcov.info" in reporting
    assert "format: lcov" in reporting
    assert "coverage-reporter-version: v0.6.22" in reporting
    assert "github-token: ${{ github.token }}" in reporting
    assert "pattern: coverage-*" in reporting
    assert "merge-multiple: true" in reporting
    assert "parallel:" not in reporting  # Both languages are one complete upload.
    assert "needs: quality" in docker
    assert "needs: coveralls" not in docker
    assert workflow.count("if-no-files-found: error") == 2
    assert workflow.count("retention-days: 7") == 2


def test_python_quality_generates_coverage_without_changing_docker_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The existing offline suite emits LCOV; coverage must not select fewer tests."""
    command = Mock()
    monkeypatch.setattr(run, "command", command)
    run.quality()
    pytest_command = command.call_args_list[2].args[0]
    assert "pytest" in pytest_command
    assert "--cov" in pytest_command
    assert "--cov-report=lcov:coverage/python.lcov" in pytest_command
    assert "-k" not in pytest_command
    assert "-m" not in pytest_command
    assert command.call_args_list[-2].args[0][-3:] == ["ruff", "check", "."]
    assert command.call_args_list[-1].args[0][-4:] == ["ruff", "format", "--check", "."]
