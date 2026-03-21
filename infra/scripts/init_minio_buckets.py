"""Ensure required MinIO buckets exist.

Run via: uv run python infra/scripts/init_minio_buckets.py

Reads host-side env vars (not the SYN_STORAGE_* vars used inside containers):
  MINIO_ROOT_USER     (default: minioadmin)   — MinIO server admin user
  MINIO_ROOT_PASSWORD (default: minioadmin)   — MinIO server admin password
  MINIO_ENDPOINT      (default: localhost:9000) — host-accessible MinIO endpoint
  SYN_STORAGE_MINIO_SECURE / MINIO_SECURE     — use HTTPS (default: false)

Retries up to MAX_ATTEMPTS times with RETRY_DELAY_SECONDS between attempts so
the script can be called immediately after `docker compose up` without racing.
"""

import os
import sys
import time

from minio import Minio
from minio.error import S3Error

BUCKETS = ["syn-artifacts", "syn-conversations"]

ENDPOINT = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "minioadmin")
SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")

_secure_env = os.environ.get("SYN_STORAGE_MINIO_SECURE", os.environ.get("MINIO_SECURE"))
SECURE: bool = _secure_env is not None and _secure_env.strip().lower() in ("1", "true", "yes", "on")

MAX_ATTEMPTS = int(os.environ.get("MINIO_INIT_MAX_ATTEMPTS", "30"))
RETRY_DELAY_SECONDS = float(os.environ.get("MINIO_INIT_RETRY_DELAY", "2"))


def main() -> None:
    client = Minio(ENDPOINT, access_key=ACCESS_KEY, secret_key=SECRET_KEY, secure=SECURE)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            for bucket in BUCKETS:
                if not client.bucket_exists(bucket):
                    client.make_bucket(bucket)
                    print(f"  ✓ Created bucket: {bucket}")
                else:
                    print(f"  · Bucket already exists: {bucket}")
            print("Buckets ready!")
            return
        except S3Error as e:
            print(f"  ✗ S3 error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:  # noqa: BLE001
            if attempt >= MAX_ATTEMPTS:
                print(
                    f"  ✗ MinIO not reachable after {MAX_ATTEMPTS} attempts: {e}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(
                f"  ⏳ MinIO not ready (attempt {attempt}/{MAX_ATTEMPTS}), retrying in {RETRY_DELAY_SECONDS:.0f}s…",
                file=sys.stderr,
            )
            time.sleep(RETRY_DELAY_SECONDS)


if __name__ == "__main__":
    main()
