"""Deterministic Lambda artifact assembly inside the actual Linux runtime image."""

import sys
import zipfile
from pathlib import Path


def build_archive(source: Path, destination: Path) -> None:
    """Keep native shared libraries and dist-info; exclude only caches and bytecode."""
    size = 0
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            data = path.read_bytes()
            size += len(data)
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), (2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    if size > 250 * 1024**2:
        raise ValueError("Unpacked Lambda package exceeds 250 MiB")


if __name__ == "__main__":
    build_archive(Path(sys.argv[1]), Path(sys.argv[2]))
