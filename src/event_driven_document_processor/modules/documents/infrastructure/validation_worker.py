"""Private decoder subprocess. Exit codes are fixed; no file-controlled diagnostics escape."""

import os
import sys
import warnings
from pathlib import Path


def validate(path: Path, mime: str, limits: tuple[int, int, int, int]) -> int:
    """Decode supported images and check PDF structure/streams without extracting text."""
    import pikepdf
    from PIL import Image, UnidentifiedImageError

    max_pixels, max_dimension, max_pages, max_objects = limits
    Image.MAX_IMAGE_PIXELS = max_pixels
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    try:
        with path.open("rb") as stream:
            head = stream.read(8)
            stream.seek(-min(path.stat().st_size, 1024), 2)
            tail = stream.read()
        if head.startswith(b"%PDF-"):
            actual = "application/pdf"
        elif head.startswith(b"\x89PNG\r\n\x1a\n"):
            actual = "image/png"
        elif head.startswith(b"\xff\xd8\xff"):
            actual = "image/jpeg"
        else:
            return 20
        if actual != mime:
            return 21
        if actual == "application/pdf":
            if not tail.rstrip().endswith(b"%%EOF"):
                return 20
            with pikepdf.open(path, attempt_recovery=False, suppress_warnings=True) as pdf:
                if pdf.is_encrypted:
                    return 20
                if len(pdf.objects) > max_objects or len(pdf.pages) > max_pages:
                    return 22
                if not pdf.pages or pdf.check_pdf_syntax() or pdf.get_warnings():
                    return 20
        else:
            # Decoder strictness includes CRC verification and a complete pixel decode.
            if actual == "image/jpeg" and not tail.endswith(b"\xff\xd9"):
                return 20
            if actual == "image/png" and not tail.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82"):
                return 20
            with Image.open(path) as image:
                if image.format != {"image/png": "PNG", "image/jpeg": "JPEG"}[actual]:
                    return 21
                if (
                    max(image.size) > max_dimension
                    or image.width * image.height > max_pixels
                    or getattr(image, "n_frames", 1) != 1
                ):
                    return 22
                image.verify()
            with Image.open(path) as image:
                image.load()
    except Image.DecompressionBombError, Image.DecompressionBombWarning, MemoryError:
        return 22
    except OSError as error:
        # Pillow uses OSError without errno for corrupt encoded pixels. Actual local
        # filesystem failures must remain retryable instead of condemning the document.
        return 23 if error.errno is not None else 20
    except (
        pikepdf.PdfError,
        pikepdf.PasswordError,
        UnidentifiedImageError,
        ValueError,
        SyntaxError,
    ):
        return 20
    return 0


def main() -> int:
    """Apply Linux process budgets before importing native parsers; Windows retains deadline."""
    if os.name == "posix":
        import resource
        import signal

        # Linux is the deployment target. Compressed files can expand far beyond byte limits.
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
        # The parent deadline is at most 60 seconds, so it can classify a stuck native
        # parser as RESOURCE_LIMIT before the emergency hard kill becomes necessary.
        resource.setrlimit(resource.RLIMIT_CPU, (10, 61))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        signal.signal(signal.SIGXCPU, lambda *_: sys.exit(22))
    return validate(Path(sys.argv[1]), sys.argv[2], tuple(int(x) for x in sys.argv[3:7]))


if __name__ == "__main__":
    sys.exit(main())
