"""GitHub App JWT generation.

Extracted from client.py to reduce module complexity.
Handles private key decoding and JWT creation for GitHub App auth.
"""

from __future__ import annotations

import base64
import logging
import time

import jwt

logger = logging.getLogger(__name__)

# JWT algorithm for GitHub App authentication
JWT_ALGORITHM = "RS256"

# JWT validity period (GitHub allows max 10 minutes)
JWT_EXPIRY_SECONDS = 10 * 60

# Clock skew buffer (issue JWT 60 seconds in the past)
CLOCK_SKEW_SECONDS = 60


def decode_private_key(encoded_key: str) -> str:
    """Decode a base64-encoded PEM private key.

    Args:
        encoded_key: Base64-encoded private key string

    Returns:
        PEM-formatted private key string.

    Raises:
        ValueError: If decoding fails.
    """
    try:
        return base64.b64decode(encoded_key).decode("utf-8")
    except Exception as e:
        msg = f"Failed to decode private key: {e}"
        raise ValueError(msg) from e


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
        "exp": now + JWT_EXPIRY_SECONDS,
        # Issuer is the App ID
        "iss": app_id,
    }

    return jwt.encode(payload, private_key, algorithm=JWT_ALGORITHM)
