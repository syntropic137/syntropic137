"""
Shared utilities for AEF infrastructure scripts.

Canonical implementations of common operations used across setup.py,
secrets_setup.py, cloudflare_tunnel.py, health_check.py, and friends.
Import from here — don't re-implement.
"""

from __future__ import annotations

import contextlib
import re
import stat
from pathlib import Path

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

# All paths are relative to the repo root, resolved from this script's location.
SCRIPTS_DIR = Path(__file__).parent.resolve()
INFRA_DIR = SCRIPTS_DIR.parent
PROJECT_ROOT = INFRA_DIR.parent
DOCKER_DIR = PROJECT_ROOT / "docker"

SECRETS_DIR = INFRA_DIR / "docker" / "secrets"
ENV_FILE = INFRA_DIR / ".env"
ENV_EXAMPLE = INFRA_DIR / ".env.example"

# ---------------------------------------------------------------------------
# Secret file names (single source of truth)
# ---------------------------------------------------------------------------

SECRET_DB_PASSWORD = "db-password.txt"
SECRET_REDIS_PASSWORD = "redis-password.txt"
SECRET_GITHUB_KEY = "github-private-key.pem"
SECRET_CF_TUNNEL_TOKEN = "cloudflare-tunnel-token.txt"

# Required auto-generated secrets: filename → byte length (2x chars in hex)
REQUIRED_SECRETS: dict[str, int] = {
    SECRET_DB_PASSWORD: 32,
    SECRET_REDIS_PASSWORD: 32,
}

# ---------------------------------------------------------------------------
# .env key constants (match infra/.env and infra/.env.example)
# ---------------------------------------------------------------------------

ENV_SYN_DOMAIN = "SYN_DOMAIN"
ENV_OP_VAULT = "OP_VAULT"
ENV_OP_SERVICE_ACCOUNT_TOKEN = "OP_SERVICE_ACCOUNT_TOKEN"
ENV_APP_ENVIRONMENT = "APP_ENVIRONMENT"
ENV_DEPLOY_ENV = "DEPLOY_ENV"
ENV_INCLUDE_OP_CLI = "INCLUDE_OP_CLI"
ENV_CLOUDFLARE_TUNNEL_TOKEN = "CLOUDFLARE_TUNNEL_TOKEN"
ENV_GITHUB_APP_ID = "SYN_GITHUB_APP_ID"
ENV_GITHUB_APP_NAME = "SYN_GITHUB_APP_NAME"
ENV_GITHUB_PRIVATE_KEY = "SYN_GITHUB_PRIVATE_KEY"
ENV_GITHUB_WEBHOOK_SECRET = "SYN_GITHUB_WEBHOOK_SECRET"

# ---------------------------------------------------------------------------
# Compose file stacking (single source of truth)
# ---------------------------------------------------------------------------

COMPOSE_BASE = DOCKER_DIR / "docker-compose.yaml"
COMPOSE_SELFHOST = DOCKER_DIR / "docker-compose.selfhost.yaml"
COMPOSE_CLOUDFLARE = DOCKER_DIR / "docker-compose.cloudflare.yaml"
COMPOSE_DEV = DOCKER_DIR / "docker-compose.dev.yaml"

# Default project name — must match docker-compose.yaml `name:` field
DEFAULT_PROJECT_NAME = "syntropic137"
ENV_COMPOSE_PROJECT_NAME = "COMPOSE_PROJECT_NAME"

# ---------------------------------------------------------------------------
# Service ports (single source of truth)
# ---------------------------------------------------------------------------

PORT_POSTGRES = 5432
PORT_EVENT_STORE = 50051
PORT_COLLECTOR = 8080
PORT_API = 8000
PORT_UI = 80
PORT_MINIO = 9000
PORT_MINIO_CONSOLE = 9001
PORT_REDIS = 6379

# ---------------------------------------------------------------------------
# .env file parsing
# ---------------------------------------------------------------------------


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into a key-value dict.

    Handles comments, blank lines, and surrounding quotes on values.
    Stdlib-only — no external dependencies.
    """
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return result
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        value = raw_value.strip()
        # Strip surrounding quotes (matched pairs only)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# File permissions
# ---------------------------------------------------------------------------


def set_secure_permissions(path: Path) -> None:
    """Set file permissions to owner read/write only (600).

    Works on Unix-like systems; silently ignored on Windows.
    """
    with contextlib.suppress(OSError, AttributeError):
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


# ---------------------------------------------------------------------------
# Domain / URL helpers
# ---------------------------------------------------------------------------


def normalize_domain(raw: str) -> str:
    """Strip protocol prefix and trailing slash from a domain string.

    Handles cases where users paste a full URL like ``https://example.com/``
    into SYN_DOMAIN.  Returns just ``example.com``.
    """
    return re.sub(r"^https?://", "", raw).rstrip("/")


def format_access_urls(domain: str) -> dict[str, str]:
    """Build the standard set of access URLs from a domain.

    Returns a dict with keys: ui, api, api_docs, openapi.
    If domain is empty, returns localhost URLs.
    """
    if domain:
        d = normalize_domain(domain)
        return {
            "ui": f"https://{d}",
            "api": f"https://{d}/api/v1",
            "api_docs": f"https://{d}/api/v1/docs",
            "openapi": f"https://{d}/api/v1/openapi.json",
        }
    return {
        "ui": f"http://localhost:{PORT_UI}",
        "api": f"http://localhost:{PORT_UI}/api/v1",
        "api_docs": f"http://localhost:{PORT_UI}/api/v1/docs",
        "openapi": f"http://localhost:{PORT_UI}/api/v1/openapi.json",
    }


# ---------------------------------------------------------------------------
# Compose file helpers
# ---------------------------------------------------------------------------


def compose_file_args(*, cloudflare: bool = False, dev: bool = False) -> list[str]:
    """Build the ``-f file1 -f file2`` args for docker compose.

    Centralises the compose overlay stacking so setup.py and justfile
    don't independently maintain the same list.
    """
    files = ["-f", str(COMPOSE_BASE)]
    if dev:
        files += ["-f", str(COMPOSE_DEV)]
    else:
        files += ["-f", str(COMPOSE_SELFHOST)]
    if cloudflare:
        files += ["-f", str(COMPOSE_CLOUDFLARE)]
    return files
