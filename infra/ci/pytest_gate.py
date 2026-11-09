"""Reject silently skipped Docker gates and any expected failure beyond the known SSE gap."""

from collections import Counter

import pytest
from _pytest.terminal import TerminalReporter

SSE_GAP = "tests/integration/test_s3_floci.py::test_post_object_reports_bucket_default_encryption"
counts: Counter[str] = Counter()
unexpected: list[str] = []


def pytest_sessionstart(session: pytest.Session) -> None:
    """Reset state even when pytest is invoked repeatedly inside a test process."""
    counts.clear()
    unexpected.clear()


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Allow only the existing strict SSE assertion xfail; skips are not execution evidence."""
    if report.skipped:
        expected = hasattr(report, "wasxfail") and report.nodeid == SSE_GAP
        counts["xfailed" if expected else "skipped"] += 1
        if not expected:
            unexpected.append(report.nodeid)
    elif report.failed:
        counts["failed" if report.when == "call" else "errors"] += 1
    elif report.when == "call":
        counts["passed"] += 1
        if hasattr(report, "wasxfail"):
            unexpected.append(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Keep ordinary failures and enforce real execution without modifying any test markers."""
    if unexpected or not counts["passed"]:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter: TerminalReporter) -> None:
    """Emit numeric-only evidence safe for the outer runner to relay from captured output."""
    values = " ".join(
        f"{key}={counts[key]}"
        for key in (
            "passed",
            "failed",
            "errors",
            "skipped",
            "xfailed",
        )
    )
    terminalreporter.write_line(f"CI_RESULT {values}")
