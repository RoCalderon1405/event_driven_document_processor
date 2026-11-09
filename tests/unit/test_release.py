"""Offline release policy, production-target selection and fail-closed registry publication."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from infra.release import publish as cd

COMMIT = "a" * 40
DIGEST = "sha256:" + "b" * 64


@pytest.fixture
def release() -> cd.Release:
    return cd.identity("Owner/Document_Processor", "v1.2.3", COMMIT)


@pytest.mark.parametrize("version", ["v0.0.0", "v1.2.3", "v2.0.0-rc.1", "v1.2.3-alpha-x"])
def test_canonical_versions(version: str) -> None:
    result = cd.identity("Owner/Repo", version, COMMIT)
    assert result.image == "ghcr.io/owner/repo"
    assert result.version == version
    assert result.commit_tag == "sha-" + COMMIT


@pytest.mark.parametrize(
    "version",
    [
        "1.2.3",
        "v1.2",
        "v01.2.3",
        "v1.02.3",
        "v1.2.03",
        "v1.2.3+build",
        "v1.2.3-01",
        "v1.2.3-a..b",
        "v1.2.3-",
        "v1.2.3-a/b",
        "v1.2.3\n",
        "v1.2.3-$(id)",
        "v1.2.3-" + "a" * 129,
        "v1.2\x002.3",
    ],
)
def test_invalid_versions_rejected(version: str) -> None:
    with pytest.raises(ValueError):
        cd.identity("Owner/Repo", version, COMMIT)


@pytest.mark.parametrize(
    "repository,commit",
    [("owner/repo/extra", COMMIT), ("bad owner/repo", COMMIT), ("owner/repo", "main")],
)
def test_invalid_identity_rejected(repository: str, commit: str) -> None:
    with pytest.raises(ValueError):
        cd.identity(repository, "v1.2.3", commit)


@pytest.mark.parametrize("event_sha", [COMMIT, "d" * 40])
def test_release_context_checks_ancestry_and_clean_exact_checkout(monkeypatch, event_sha) -> None:
    for key, value in {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF_TYPE": "tag",
        "GITHUB_REPOSITORY": "Owner/Repo",
        "GITHUB_REF_NAME": "v1.2.3",
        "GITHUB_SHA": event_sha,
    }.items():
        monkeypatch.setenv(key, value)
    execute = Mock(side_effect=[COMMIT, COMMIT, COMMIT, "", ""])
    monkeypatch.setattr(cd, "execute", execute)
    assert cd.context().commit == COMMIT
    assert execute.call_args_list[0].args[0] == ["git", "rev-parse", f"{event_sha}^{{commit}}"]
    assert execute.call_args_list[3].args[0] == [
        "git",
        "merge-base",
        "--is-ancestor",
        COMMIT,
        "origin/master",
    ]
    execute.side_effect = [COMMIT, COMMIT, COMMIT, "", " M Dockerfile"]
    with pytest.raises(ValueError):
        cd.context()
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    with pytest.raises(ValueError):
        cd.context()


def test_build_is_runtime_not_last_dockerfile_stage(monkeypatch, release) -> None:
    execute = Mock(
        side_effect=["", json.dumps([{"Config": {"User": "app", "Cmd": ["uvicorn"]}}]), ""]
    )
    monkeypatch.setattr(cd, "execute", execute)
    cd.build(release)
    args = execute.call_args_list[0].args[0]
    assert args[args.index("--target") + 1] == "runtime"
    assert args[args.index("--platform") + 1] == "linux/amd64"
    assert f"org.opencontainers.image.revision={COMMIT}" in args
    assert "--network" in execute.call_args_list[2].args[0]


@pytest.mark.parametrize(
    "status,headers,expected",
    [
        (404, {}, None),
        (200, {"Docker-Content-Digest": DIGEST}, DIGEST),
    ],
)
def test_registry_manifest_absence_and_digest(
    monkeypatch, release, status, headers, expected
) -> None:
    monkeypatch.setattr(cd, "request", Mock(return_value=(status, headers, b"")))
    assert cd.manifest(release, "v1.2.3", "secret") == expected


@pytest.mark.parametrize("status", [401, 403, 429, 500, 200])
def test_registry_errors_never_mean_missing(monkeypatch, release, status) -> None:
    monkeypatch.setattr(cd, "request", Mock(return_value=(status, {}, b"")))
    with pytest.raises(RuntimeError):
        cd.manifest(release, "v1.2.3", "secret")


@pytest.fixture
def publisher(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        cd,
        "request",
        Mock(
            return_value=(
                200,
                {},
                json.dumps(
                    {
                        "object": {"type": "commit", "sha": COMMIT},
                    }
                ).encode(),
            )
        ),
    )
    monkeypatch.setattr(cd, "bearer", Mock(return_value="registry-secret"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    execute = Mock(return_value=f"digest: {DIGEST}")
    monkeypatch.setattr(cd, "execute", execute)
    return execute, tmp_path / "summary.md"


@pytest.mark.parametrize("existing", [[DIGEST], [None, DIGEST]])
def test_duplicate_version_or_commit_cannot_push(monkeypatch, release, publisher, existing) -> None:
    execute, summary = publisher
    monkeypatch.setattr(cd, "manifest", Mock(side_effect=existing))
    with pytest.raises(ValueError, match="already exists"):
        cd.publish(release, "private-token", "actor")
    execute.assert_not_called()
    assert not summary.exists()


def test_success_records_matching_remote_digests_without_logging_token(
    monkeypatch,
    release,
    publisher,
    capsys,
) -> None:
    execute, summary = publisher
    monkeypatch.setattr(cd, "manifest", Mock(side_effect=[None, None, DIGEST, DIGEST]))
    cd.publish(release, "private-token", "actor")
    assert f"{release.image}@{DIGEST}" in summary.read_text()
    assert "private-token" not in capsys.readouterr().out
    login = execute.call_args_list[0]
    assert login.kwargs["secret_input"] == "private-token"
    assert "RELEASE_TOKEN" not in login.kwargs["env"]
    assert not Path(login.kwargs["env"]["DOCKER_CONFIG"]).exists()
    pushes = [call.args[0][-1] for call in execute.call_args_list if call.args[0][1] == "push"]
    assert pushes == [f"{release.image}:{release.commit_tag}", f"{release.image}:v1.2.3"]


def test_moved_remote_tag_stops_publication(monkeypatch, release, publisher) -> None:
    execute, _ = publisher
    cd.request.return_value = (200, {}, b'{"object":{"type":"commit","sha":"wrong"}}')
    with pytest.raises(ValueError, match="moved"):
        cd.publish(release, "secret", "actor")
    execute.assert_not_called()


def test_partial_push_failure_cannot_report_success(monkeypatch, release, publisher) -> None:
    execute, summary = publisher
    execute.side_effect = ["", "", f"digest: {DIGEST}", "", RuntimeError("push failed")]
    monkeypatch.setattr(cd, "manifest", Mock(side_effect=[None, None]))
    with pytest.raises(RuntimeError):
        cd.publish(release, "secret", "actor")
    assert not summary.exists()


def test_digest_mismatch_cannot_report_success(monkeypatch, release, publisher) -> None:
    _, summary = publisher
    monkeypatch.setattr(cd, "manifest", Mock(side_effect=[None, None, "sha256:" + "c" * 64]))
    with pytest.raises(RuntimeError, match="same verified digest"):
        cd.publish(release, "secret", "actor")
    assert not summary.exists()


def test_credentials_cannot_leave_github_hosts() -> None:
    with pytest.raises(ValueError):
        cd.request("https://example.com/token", "Bearer secret")
