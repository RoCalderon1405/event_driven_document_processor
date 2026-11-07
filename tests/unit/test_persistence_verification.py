"""Keep the restart verifier robust to transient connections during API startup."""

import runpy
from http.client import RemoteDisconnected
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def verifier() -> dict:
    return runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "infra/local/verify_persistence.py")
    )


def test_health_poll_retries_connection_reset(
    verifier: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    poll = verifier["wait_for_api"]
    request = Mock(side_effect=[RemoteDisconnected("restarting"), {"status": "healthy"}])
    monkeypatch.setitem(poll.__globals__, "request", request)
    monkeypatch.setattr(verifier["time"], "sleep", Mock())
    poll()
    assert request.call_count == 2


def test_health_poll_has_bounded_attempts(verifier: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    poll = verifier["wait_for_api"]
    request = Mock(side_effect=ConnectionRefusedError())
    monkeypatch.setitem(poll.__globals__, "request", request)
    monkeypatch.setattr(verifier["time"], "sleep", Mock())
    with pytest.raises(RuntimeError, match="did not become healthy"):
        poll()
    assert request.call_count == 60
