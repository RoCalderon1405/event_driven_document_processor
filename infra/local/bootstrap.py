"""Run local DynamoDB and S3 provisioning in the existing one-shot Compose service."""

import runpy
import sys
from pathlib import Path


def main() -> int:
    """Stop immediately if either bootstrap fails; never reset development data."""
    for name in ("init_dynamodb.py", "init_s3.py"):
        initialize = runpy.run_path(str(Path(__file__).with_name(name)))["main"]
        if initialize() != 0:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
