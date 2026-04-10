"""GitHub App JWT generation.

Extracted from client.py to reduce module complexity.
Handles private key decoding and JWT creation for GitHub App auth.
"""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path

import jwt

logger = logging.getLogger(__name__)

# JWT algorithm for GitHub App authentication
JWT_ALGORITHM = "RS256"

# JWT validity period (GitHub allows max 10 minutes)
JWT_EXPIRY_SECONDS = 10 * 60

# Clock skew buffer (issue JWT 60 seconds in the past)
CLOCK_SKEW_SECONDS = 60

# Format detection constants
_FILE_PREFIX = "file:"
_PEM_HEADER = "-----BEGIN"


def decode_private_key(key: str) -> str:
    """Resolve a private key from a file reference, raw PEM, or base64.

    Supports three formats (checked in order):
      1. ``file:<path>`` — read PEM from file (relative paths resolve from CWD)
      2. Value starting with ``-----BEGIN`` — raw PEM, returned as-is
      3. Base64-encoded PEM string — decoded and returned

    Args:
        key: Private key in any of the supported formats.

    Returns:
        PEM-formatted private key string.

    Raises:
        ValueError: If the key cannot be resolved.
    """
    stripped = key.strip()

    if stripped.startswith(_FILE_PREFIX):
        return _read_key_file(stripped[len(_FILE_PREFIX) :])

    if stripped.startswith(_PEM_HEADER):
        return stripped

    try:
        return base64.b64decode(stripped).decode("utf-8")
    except Exception as e:
        msg = f"Failed to decode private key: {e}"
        raise ValueError(msg) from e


def _read_key_file(raw_path: str) -> str:
    """Read a PEM private key from a file path.

    Args:
        raw_path: File path (may have leading/trailing whitespace).
            Relative paths resolve from CWD.

    Returns:
        PEM file contents.

    Raises:
        ValueError: If file does not exist, is not readable, or
            does not contain a PEM header.
    """
    path = Path(raw_path.strip())
    if not path.is_absolute():
        path = Path.cwd() / path

    if not path.exists():
        msg = f"Private key file not found: {path}"
        raise ValueError(msg)

    if not path.is_file():
        msg = f"Private key path is not a file: {path}"
        raise ValueError(msg)

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        msg = f"Cannot read private key file {path}: {e}"
        raise ValueError(msg) from e

    if _PEM_HEADER not in content:
        msg = f"Private key file {path} does not contain a valid PEM header"
        raise ValueError(msg)

    return content


def generate_jwt(app_id: str, private_key: str) -> str:
    """Generate a JWT for GitHub App authentication.

    The JWT is signed with the private key and used to
    request installation access tokens.

    Args:
        app_id: The GitHub App ID
        private_key: PEM-formatted private key string

    Returns:
        Signed JWT string (valid for 10 minutes).

    Raises:
        jwt.PyJWTError: If JWT generation fails.
    """
    now = int(time.time())

    payload = {
        # Issued at (with clock skew buffer)
        "iat": now - CLOCK_SKEW_SECONDS,
        # Expires in 10 minutes
        "exp": now + JWT_EXPIRY_SECONDS - CLOCK_SKEW_SECONDS,
        # Issuer is the App ID
        "iss": app_id,
    }

    return jwt.encode(payload, private_key, algorithm=JWT_ALGORITHM)
