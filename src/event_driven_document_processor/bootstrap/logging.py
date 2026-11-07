"""Minimal logging configuration without verbose SDK request/payload logging."""

import logging


def configure_logging(level: str) -> None:
    """Configure application logs while suppressing SDK wire/debug output."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("event_driven_document_processor").setLevel(level)
    for name in ("boto3", "botocore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
