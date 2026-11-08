"""Packaging/safety utilities for disposable probes, not business processing code."""

import importlib.util
import io
import zipfile
from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlsplit

SDK_MODULES = ("boto3", "botocore", "dateutil", "jmespath", "s3transfer", "six", "urllib3")


def validate_endpoint(endpoint: str) -> str:
    """Refuse implicit AWS endpoints and credential-bearing URLs before any SDK call."""
    url = urlsplit(endpoint)
    if (
        url.scheme != "http"
        or url.hostname not in {"lambda-floci", "localhost", "127.0.0.1"}
        or url.username is not None
        or url.password is not None
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        raise ValueError("Lambda probes require an explicit local HTTP emulator endpoint")
    return endpoint.rstrip("/")


def build_probe_zip() -> bytes:
    """Vendor the installed, locked pure-Python SDK without host virtualenv/native files."""
    entries = {"lambda_handler.py": Path(__file__).with_name("lambda_handler.py").read_bytes()}
    for name in SDK_MODULES:
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            raise RuntimeError(f"Missing probe SDK module: {name}")
        source = Path(spec.origin)
        # six presents a synthetic __path__ under some import hooks; it is still one file.
        if source.name != "__init__.py":
            entries[source.name] = source.read_bytes()
            continue
        root = source.parent
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            entries[f"{name}/{path.relative_to(root).as_posix()}"] = path.read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    payload = buffer.getvalue()
    if len(payload) >= 50 * 1024 * 1024:
        raise ValueError("Probe ZIP exceeds Lambda's direct-upload limit")
    return payload


def wait_for[T](predicate: Callable[[], T | None], *, timeout: float = 90) -> T:
    """Poll a narrow assertion predicate with a deadline; never hide SDK failures."""
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        result = predicate()
        if result is not None:
            return result
        sleep(0.25)
    raise TimeoutError("Lambda compatibility assertion did not converge before its deadline")
