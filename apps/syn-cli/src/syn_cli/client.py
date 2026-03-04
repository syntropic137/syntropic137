"""Shared HTTP client for syn-api server."""

from __future__ import annotations

import os
from typing import Any

import httpx


def get_api_url() -> str:
    """Get the API server URL from environment."""
    return os.environ.get(
        "SYN_API_URL", os.environ.get("SYN_DASHBOARD_URL", "http://localhost:8000")
    )


def get_client(**kwargs: Any) -> httpx.Client:
    """Create an HTTP client configured for the syn-api server."""
    return httpx.Client(base_url=get_api_url(), timeout=30.0, **kwargs)
