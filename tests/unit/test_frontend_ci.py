"""Guard the small frontend workflow and its read-only, non-publishing boundary."""

import re
from pathlib import Path

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
        "npm test",
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
