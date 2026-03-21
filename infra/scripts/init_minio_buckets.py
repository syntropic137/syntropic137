"""Ensure required MinIO buckets exist.

Run via: uv run python infra/scripts/init_minio_buckets.py

Reads the same env vars used by Docker Compose so no extra config is needed:
  MINIO_ROOT_USER     (default: minioadmin)
  MINIO_ROOT_PASSWORD (default: minioadmin)
  MINIO_ENDPOINT      (default: localhost:9000)
"""

import os
import sys

from minio import Minio
from minio.error import S3Error

BUCKETS = ["syn-artifacts", "syn-conversations"]

ENDPOINT = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "minioadmin")
SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")


def main() -> None:
    client = Minio(ENDPOINT, access_key=ACCESS_KEY, secret_key=SECRET_KEY, secure=False)

    for bucket in BUCKETS:
        try:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
                print(f"  ✓ Created bucket: {bucket}")
            else:
                print(f"  · Bucket already exists: {bucket}")
        except S3Error as e:
            print(f"  ✗ Failed to create bucket '{bucket}': {e}", file=sys.stderr)
            sys.exit(1)

    print("Buckets ready!")


if __name__ == "__main__":
    main()
