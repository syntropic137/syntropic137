"""1Password CLI interaction layer.

Extracted from op_resolver.py to reduce module complexity.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)


def op_available() -> bool:
    """Return True if `op` CLI is installed and authenticated."""
    if not shutil.which("op"):
        return False

    if os.environ.get("OP_SERVICE_ACCOUNT_TOKEN") or os.environ.get("OP_SESSION"):
        return True

    try:
        result = subprocess.run(
            ["op", "whoami"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def fetch_op_item(vault: str, item_title: str) -> dict | None:
    """Fetch an item from a 1Password vault.

    Returns the parsed JSON item dict, or None on any failure.
    """
    try:
        result = subprocess.run(
            ["op", "item", "get", item_title, "--vault", vault, "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Timed out fetching 1Password item %s", item_title)
        return None
    except OSError as exc:
        logger.warning("Error fetching 1Password item %s: %s", item_title, exc)
        return None

    if result.returncode != 0:
        logger.warning(
            "Failed to fetch 1Password item %s from vault %s: %s",
            item_title,
            vault,
            result.stderr.strip(),
        )
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger.warning("Could not parse 1Password item response: %s", exc)
        return None


def inject_fields(item: dict) -> int:
    """Inject 1Password item fields into os.environ (without overwriting).

    Returns the number of fields injected.
    """
    injected = 0
    for field in item.get("fields", []):
        label = field.get("label", "").strip()
        value = field.get("value", "")
        if label and value and not os.environ.get(label):
            os.environ[label] = value
            injected += 1
    return injected
