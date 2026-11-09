"""Publish a validated runtime image without overwriting version or commit tags."""

import argparse
import base64
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

from infra.ci.run import ROOT, clean_environment

SEMVER = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
ACCEPT = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)


@dataclass(frozen=True)
class Release:
    """Validated, shell-safe release identity; version tags retain their leading v."""

    repository: str
    version: str
    commit: str

    @property
    def image(self) -> str:
        """Use GHCR's required lowercase namespace derived from the GitHub repository."""
        return f"ghcr.io/{self.repository.lower()}"

    @property
    def commit_tag(self) -> str:
        """Keep all forty commit characters; never publish a moving short-SHA alias."""
        return f"sha-{self.commit}"

    @property
    def local_image(self) -> str:
        """Name the production build only within this disposable publishing runner."""
        return f"eddp-release:{self.commit}"


def identity(repository: str, version: str, commit: str) -> Release:
    """Accept canonical stable/prerelease SemVer that can be represented by a Docker tag."""
    match = SEMVER.fullmatch(version)
    if not match or len(version) > 128:
        raise ValueError("Require vMAJOR.MINOR.PATCH[-prerelease], without build metadata")
    if match[4] and any(
        not part or (part.isdigit() and len(part) > 1 and part.startswith("0"))
        for part in match[4].split(".")
    ):
        raise ValueError("Invalid SemVer prerelease identifiers")
    if not SHA.fullmatch(commit) or not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository or commit identity")
    return Release(repository, version, commit)


def execute(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    secret_input: str | None = None,
    timeout: int = 120,
) -> str:
    """Never forward credentials, build output or raw registry failures to workflow logs."""
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            args,
            cwd=ROOT,
            env=env or clean_environment(),
            input=secret_input,
            text=True,
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Release subprocess failed; raw diagnostics withheld")
        output.seek(0)
        return output.read().decode("utf-8", errors="replace")


def context() -> Release:
    """Require an actual tag-push checkout reachable from the real default branch master."""
    if os.environ.get("GITHUB_EVENT_NAME") != "push" or os.environ.get("GITHUB_REF_TYPE") != "tag":
        raise ValueError("Publication requires a tag push event")
    release = identity(
        os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_REF_NAME"], os.environ["GITHUB_SHA"]
    )
    # Normalize an annotated tag object as well as an already-peeled event commit.
    commit = execute(["git", "rev-parse", f"{release.commit}^{{commit}}"]).strip()
    release = identity(release.repository, release.version, commit)
    if execute(["git", "rev-parse", "HEAD"]).strip() != release.commit:
        raise ValueError("Checkout does not match the event commit")
    tagged = execute(["git", "rev-parse", f"refs/tags/{release.version}^{{commit}}"])
    if tagged.strip() != release.commit:
        raise ValueError("Tag does not resolve to the event commit")
    execute(["git", "merge-base", "--is-ancestor", release.commit, "origin/master"])
    if execute(["git", "status", "--porcelain"]).strip():
        raise ValueError("Release checkout must be clean")
    return release


def build(release: Release) -> None:
    """Build only Linux/amd64 runtime, label its provenance and inspect production invariants."""
    execute(
        [
            "docker",
            "build",
            "--platform",
            "linux/amd64",
            "--target",
            "runtime",
            "--label",
            f"org.opencontainers.image.source=https://github.com/{release.repository}",
            "--label",
            f"org.opencontainers.image.revision={release.commit}",
            "--label",
            f"org.opencontainers.image.version={release.version}",
            "--tag",
            release.local_image,
            ".",
        ],
        timeout=660,
    )
    config = json.loads(execute(["docker", "image", "inspect", release.local_image]))[0]["Config"]
    if config["User"] != "app" or config["Cmd"][0] != "uvicorn":
        raise ValueError("Expected the non-root production API image")
    execute(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python",
            release.local_image,
            "-c",
            "import importlib.util; "
            "from event_driven_document_processor.main import app; "
            "assert app; assert importlib.util.find_spec('pytest') is None; "
            "assert importlib.util.find_spec('ruff') is None",
        ]
    )
    print("PASS: production runtime built and inspected")


def request(
    url: str,
    authorization: str,
    *,
    method: str = "GET",
) -> tuple[int, dict[str, str], bytes]:
    """Bound authenticated reads to GitHub/GHCR, without credential-bearing redirects or logs."""
    # All URLs are constructed here, never taken from untrusted HTTP Location/Link headers.
    from urllib.request import HTTPRedirectHandler, build_opener

    class NoRedirect(HTTPRedirectHandler):
        """Never forward an Authorization header to a redirected endpoint."""

        def redirect_request(
            self,
            req: Request,
            fp: Any,
            code: int,
            msg: str,
            headers: Any,
            newurl: str,
        ) -> None:
            return None

    target = urlsplit(url)
    if target.scheme != "https" or target.netloc not in {"ghcr.io", "api.github.com"}:
        raise ValueError("Refusing credentials to a non-GitHub endpoint")
    accept = "application/vnd.github+json" if target.netloc == "api.github.com" else ACCEPT
    req = Request(
        url,
        headers={"Authorization": authorization, "Accept": accept, "User-Agent": "eddp-release"},
        method=method,
    )
    try:
        with build_opener(NoRedirect).open(req, timeout=30) as response:
            return response.status, dict(response.headers), response.read(1024 * 1024)
    except HTTPError as error:
        if error.code == 404:
            return 404, {}, b""
        raise RuntimeError(f"Registry/GitHub request refused (HTTP {error.code})") from None
    except URLError, TimeoutError:
        raise RuntimeError("Registry/GitHub request unavailable") from None


def bearer(release: Release, actor: str, token: str) -> str:
    """Exchange the job-scoped GITHUB_TOKEN for a repository-scoped registry bearer token."""
    basic = base64.b64encode(f"{actor}:{token}".encode()).decode()
    query = urlencode(
        {"service": "ghcr.io", "scope": f"repository:{release.repository.lower()}:pull,push"}
    )
    status, _, body = request(f"https://ghcr.io/token?{query}", f"Basic {basic}")
    if status != 200:
        raise RuntimeError("Registry token exchange failed")
    return json.loads(body)["token"]


def manifest(release: Release, tag: str, auth: str) -> str | None:
    """Only an authenticated 404 proves absence; authorization and transport errors stop release."""
    status, headers, _ = request(
        f"https://ghcr.io/v2/{release.repository.lower()}/manifests/{tag}",
        f"Bearer {auth}",
        method="HEAD",
    )
    if status == 404:
        return None
    digest = next(
        (value for key, value in headers.items() if key.lower() == "docker-content-digest"), ""
    )
    if status != 200 or not DIGEST.fullmatch(digest):
        raise RuntimeError("Registry returned no valid image digest")
    return digest


def publish(release: Release, token: str, actor: str) -> None:
    """Refuse existing tags, push commit then version, and record verified registry digests."""
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\[bot\])?", actor):
        raise ValueError("Require the job token and a valid GitHub actor")
    # Re-read the remote ref after CI; a moved tag must not publish the older validated commit.
    status, _, raw = request(
        f"https://api.github.com/repos/{release.repository}/git/ref/tags/{release.version}",
        f"Bearer {token}",
    )
    if status != 200:
        raise RuntimeError("Release tag no longer exists")
    obj = json.loads(raw)["object"]
    for _ in range(5):
        if obj["type"] == "commit":
            break
        if obj["type"] != "tag" or not SHA.fullmatch(obj["sha"]):
            raise ValueError("Invalid remote tag object")
        _, _, raw = request(
            f"https://api.github.com/repos/{release.repository}/git/tags/{obj['sha']}",
            f"Bearer {token}",
        )
        obj = json.loads(raw)["object"]
    if obj.get("type") != "commit" or obj.get("sha") != release.commit:
        raise ValueError("Remote release tag moved after validation")
    auth = bearer(release, actor, token)
    tags = (release.commit_tag, release.version)
    if any(manifest(release, tag, auth) is not None for tag in tags):
        raise ValueError(
            "Release/commit tag already exists; refusing overwrite or duplicate release"
        )
    with tempfile.TemporaryDirectory(prefix="eddp-ghcr-") as directory:
        env = clean_environment() | {"DOCKER_CONFIG": directory}
        execute(
            ["docker", "login", "ghcr.io", "--username", actor, "--password-stdin"],
            env=env,
            secret_input=token,
        )
        digests = []
        for tag in tags:
            target = f"{release.image}:{tag}"
            execute(["docker", "tag", release.local_image, target], env=env)
            output = execute(["docker", "push", target], env=env, timeout=180)
            matches = re.findall(r"digest: (sha256:[0-9a-f]{64})", output)
            if len(matches) != 1:
                raise RuntimeError("Push returned no unambiguous image digest")
            digests.append(matches[0])
        if len(set(digests)) != 1 or any(
            manifest(release, tag, auth) != digests[0] for tag in tags
        ):
            raise RuntimeError("Published tags do not resolve to the same verified digest")
    digest = digests[0]
    summary = (
        f"## Runtime image published\n\n- Version: `{release.image}:{release.version}`\n"
        f"- Commit: `{release.image}:{release.commit_tag}`\n"
        f"- Pull by digest: `{release.image}@{digest}`\n"
    )
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
        stream.write(summary)
    print(summary)


def main() -> int:
    """Separate no-token checks/builds from the only operation allowed registry write access."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "build", "publish"))
    operation = parser.parse_args().operation
    try:
        release = context()
        if operation == "build":
            build(release)
        elif operation == "publish":
            publish(release, os.environ.get("RELEASE_TOKEN", ""), os.environ["GITHUB_ACTOR"])
        else:
            print("PASS: canonical release tag, commit and master ancestry")
    except ValueError, RuntimeError, OSError, KeyError, subprocess.TimeoutExpired:
        print("FAIL: release refused; check ref/provenance, duplicate tags and package permissions")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
