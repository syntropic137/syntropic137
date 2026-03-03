"""
Cloudflare Tunnel helpers for the Syn137 setup wizard.

Handles token extraction, persistence, and dashboard URL construction.
Follows the same pattern as ``github_manifest.py`` — pure logic that the
setup wizard orchestrates, no direct user I/O.

Why a separate module?
  The Cloudflare onboarding flow has its own quirks (token embedded in a
  shell command, deep-link URLs that need an account ID, etc.).  Keeping
  this logic isolated makes it testable and keeps setup.py focused on
  stage orchestration rather than vendor-specific parsing.
"""

from __future__ import annotations

import os
from pathlib import Path

from shared import SECRET_CF_TUNNEL_TOKEN, set_secure_permissions

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Zero Trust dashboard — Cloudflare handles login/signup/account routing.
DASHBOARD_URL = "https://one.dash.cloudflare.com"


# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------


def extract_token(raw: str) -> str:
    """Extract the tunnel token from raw user input.

    Buttery onboarding: Cloudflare doesn't let you copy the token directly.
    They show a full shell command like::

        cloudflared service install eyJhIjoi...
        sudo cloudflared service install eyJhIjoi...

    Rather than making the user manually find the eyJ... part, we accept
    whatever they paste and pull the token out ourselves.
    Zero friction > zero ambiguity.

    Args:
        raw: The raw string the user pasted — could be a bare token or a
             full ``cloudflared service install <token>`` command.

    Returns:
        The extracted token string, or empty string if input was empty.
    """
    raw = raw.strip()
    if not raw:
        return ""
    # Walk backwards through whitespace-separated parts.
    # The token is always the last argument and starts with eyJ
    # (base64-encoded JSON: {"a":...).
    for part in reversed(raw.split()):
        if part.startswith("eyJ"):
            return part
    # No eyJ prefix found — assume they pasted the bare token directly
    return raw


# ---------------------------------------------------------------------------
# Dashboard URL
# ---------------------------------------------------------------------------


def dashboard_url(account_id: str = "") -> str:
    """Build the best Cloudflare dashboard URL we can.

    If we have the account ID (from env or .env), deep-link straight to
    Networks > Connectors.  Otherwise return the generic dashboard and let
    Cloudflare handle account routing after login.

    Args:
        account_id: Optional Cloudflare account ID (32-char hex string).
                    Falls back to ``CLOUDFLARE_ACCOUNT_ID`` env var.

    Returns:
        The dashboard URL string.
    """
    acct = account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if acct:
        return f"{DASHBOARD_URL}/{acct}/networks/connectors"
    return DASHBOARD_URL


# ---------------------------------------------------------------------------
# Token persistence
# ---------------------------------------------------------------------------


def write_token(token: str, secrets_dir: Path) -> Path:
    """Write the tunnel token to the Docker secret file.

    This is the file that docker-compose mounts into the cloudflared
    container.  Writing it here closes the critical gap where the old
    wizard collected the token but never persisted it to disk.

    Args:
        token: The raw tunnel token (will be stripped of whitespace).
        secrets_dir: Path to the Docker secrets directory.

    Returns:
        The path where the token was written.
    """
    secrets_dir.mkdir(parents=True, exist_ok=True)
    token_path = secrets_dir / SECRET_CF_TUNNEL_TOKEN
    token_path.write_text(token.strip())
    set_secure_permissions(token_path)
    return token_path
