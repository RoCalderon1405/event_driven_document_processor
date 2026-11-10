"""Reproduce CI with isolated Compose projects and numeric-only, payload-free diagnostics."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".ci-state.json"
PROJECT = re.compile(r"eddp-ci-[a-f0-9]{16}-(regression|events)\Z")
RESULT = re.compile(r"CI_RESULT passed=\d+ failed=\d+ errors=\d+ skipped=\d+ xfailed=\d+")


def clean_environment() -> dict[str, str]:
    """Allow OS/Docker connectivity only, not inherited AWS, Compose, uv or app overrides."""
    allowed = {
        "PATH",
        "HOME",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "TEMP",
        "TMP",
        "PROGRAMDATA",
        "PATHEXT",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    result = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    result.update(
        {
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
            "AWS_DEFAULT_REGION": "us-east-1",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
            "AWS_CONFIG_FILE": os.devnull,
            "UV_NO_CONFIG": "true",
            "UV_PYTHON": "3.14",
            "PYTHONUTF8": "1",
            "COMPOSE_DISABLE_ENV_FILE": "1",
            "NO_COLOR": "1",
        }
    )
    return result


def command(args: list[str], label: str, *, timeout: int = 300) -> str:
    """Capture SDK/build/test output privately; relay no tracebacks, request bodies or URLs."""
    print(f"RUN: {label}", flush=True)
    # TemporaryFile avoids unbounded RAM and deletes raw diagnostics even after a failed gate.
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(
                args,
                cwd=ROOT,
                env=clean_environment(),
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"{label}: {type(error).__name__}") from None
        output.seek(0)
        text = output.read().decode("utf-8", errors="replace")
    for summary in RESULT.findall(text):
        print(summary, flush=True)
    if result.returncode:
        raise RuntimeError(f"{label}: exit {result.returncode}; reproduce locally for diagnostics")
    print(f"PASS: {label}", flush=True)
    return text


def compose(project: str) -> list[str]:
    """Build a fixed file/env command only for a generated, tightly validated project name."""
    if not PROJECT.fullmatch(project):
        raise ValueError("Refusing non-CI Compose project")
    suite = project.rsplit("-", 1)[1]
    base = "compose.yaml" if suite == "regression" else "compose.lambda.yaml"
    return [
        "docker",
        "compose",
        "--env-file",
        "infra/ci/empty.env",
        "--project-name",
        project,
        "-f",
        base,
        "-f",
        f"infra/ci/compose.{suite}.yaml",
        "--profile",
        "*",
    ]


def validate_config(config: dict, project: str) -> None:
    """Fail closed before starting services if resolved configuration could touch local data."""
    if config.get("name") != project:
        raise ValueError("Compose project mismatch")
    for name, service in config["services"].items():
        if service.get("ports") or service.get("container_name") or service.get("privileged"):
            raise ValueError("CI must not publish ports or use fixed/privileged containers")
        for mount in service.get("volumes", []):
            if name != "lambda-floci" or mount["type"] != "bind":
                raise ValueError("CI must not mount persistent data")
            target = mount["target"]
            if target == "/var/run/docker.sock" and mount["source"] == "/var/run/docker.sock":
                continue
            probe = ROOT / "infra/compatibility/probe-runtime.yaml"
            if (
                target == "/etc/floci/probe-runtime.yaml"
                and mount.get("read_only")
                and Path(mount["source"]).resolve() == probe.resolve()
            ):
                continue
            raise ValueError("Unexpected CI bind mount")
        if name in {"floci", "lambda-floci"}:
            if service["environment"].get("FLOCI_STORAGE_MODE") != "memory":
                raise ValueError("CI emulator must be ephemeral")
        if name == "lambda-floci":
            env = service["environment"]
            if (
                env["FLOCI_DOCKER_RESOURCE_NAMESPACE"] != project
                or env["FLOCI_SERVICES_LAMBDA_DOCKER_NETWORK"] != f"{project}_lambda_probe"
            ):
                raise ValueError("Lambda resources must belong to this CI project")
    for network in config.get("networks", {}).values():
        if network.get("external") or not network["name"].startswith(project + "_"):
            raise ValueError("CI must not share development networks")


def load_projects() -> list[str]:
    """Read only our exact two-project state format; never accept arbitrary cleanup targets."""
    data = json.loads(STATE.read_text())
    if (
        not isinstance(data, list)
        or len(data) != 2
        or any(not isinstance(item, str) or not PROJECT.fullmatch(item) for item in data)
    ):
        raise ValueError("Invalid CI cleanup state")
    if data[0].removesuffix("-regression") != data[1].removesuffix("-events"):
        raise ValueError("Mismatched CI cleanup projects")
    if not data[0].endswith("-regression") or not data[1].endswith("-events"):
        raise ValueError("Invalid CI cleanup order")
    return data


def cleanup() -> None:
    """Stop this run only; no volume removal, image deletion, global prune or prefix cleanup."""
    if not STATE.exists():
        return
    failed = False
    for project in reversed(load_projects()):
        try:
            command(
                compose(project) + ["down", "--remove-orphans", "--timeout", "15"],
                "cleanup " + project.rsplit("-", 1)[1],
                timeout=75,
            )
        except RuntimeError:
            failed = True
    if failed:
        raise RuntimeError("CI cleanup failed; state retained for a scoped retry")
    STATE.unlink()


def docker_gates() -> None:
    """Validate and build both isolated stacks, then explicitly execute every opt-in suite."""
    version = command(["docker", "compose", "version", "--short"], "Compose version")
    numbers = re.search(r"(\d+)\.(\d+)\.(\d+)", version)
    if not numbers or tuple(map(int, numbers.groups())) < (2, 24, 4):
        raise RuntimeError("Docker Compose >= 2.24.4 is required for !override/!reset")
    prefix = f"eddp-ci-{uuid4().hex[:16]}"
    projects = [prefix + "-regression", prefix + "-events"]
    # Exclusive creation prevents concurrent local runs from stealing each other's cleanup state.
    with STATE.open("x") as stream:
        json.dump(projects, stream)
    try:
        for project in projects:
            raw = command(compose(project) + ["config", "--format", "json"], "Compose resolution")
            validate_config(json.loads(raw), project)
        normal, events = map(compose, projects)
        command(
            normal + ["build", "api", "dynamodb-bootstrap", "tests"],
            "runtime/test images",
            timeout=600,
        )
        command(
            events + ["build", "lambda-tests", "event-tests", "processing-bootstrap"],
            "native Lambda and event images",
            timeout=900,
        )
        pytest = [
            "uv",
            "run",
            "--no-sync",
            "pytest",
            "-p",
            "infra.ci.pytest_gate",
            "-q",
            "--tb=no",
            "--show-capture=no",
        ]
        command(
            normal + ["run", "--rm", "tests", *pytest, "tests/unit", "tests/integration"],
            "Floci regression",
            timeout=300,
        )
        command(
            events + ["run", "--rm", "lambda-tests", *pytest, "tests/compatibility"],
            "Lambda compatibility",
            timeout=300,
        )
        command(
            events + ["run", "--rm", "event-tests", *pytest, "tests/events"],
            "real S3/SQS/Lambda events",
            timeout=900,
        )
    finally:
        cleanup()


def quality() -> None:
    """Run the entire offline suite and full lint/format checks from the unchanged lockfile."""
    command(["uv", "sync", "--locked"], "locked dependency sync")
    command(
        [
            "uv",
            "run",
            "--no-sync",
            "python",
            "-c",
            "import sys; assert sys.version_info[:2] == (3, 14)",
        ],
        "Python 3.14",
    )
    command(
        [
            "uv",
            "run",
            "--no-sync",
            "pytest",
            "-q",
            "--tb=no",
            "--show-capture=no",
            "--cov",
            "--cov-report=term-missing",
            "--cov-report=lcov:coverage/python.lcov",
        ],
        "offline pytest with application coverage",
    )
    command(["uv", "run", "--no-sync", "ruff", "check", "."], "Ruff lint")
    command(["uv", "run", "--no-sync", "ruff", "format", "--check", "."], "full formatting")


def main() -> int:
    """Expose the same bounded commands to GitHub Actions and local Linux/Windows users."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", choices=("quality", "docker", "cleanup"))
    args = parser.parse_args()
    try:
        {"quality": quality, "docker": docker_gates, "cleanup": cleanup}[args.gate]()
    except (RuntimeError, ValueError, FileExistsError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
