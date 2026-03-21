"""Shared HTTP client for syn-api server."""

from __future__ import annotations

import os
from typing import Any

import httpx


def get_api_url() -> str:
    """Get the API server URL from environment."""
    return os.environ.get("SYN_API_URL", "http://localhost:8137")


def get_client(**kwargs: Any) -> httpx.Client:
    """Create an HTTP client configured for the syn-api server."""
    return httpx.Client(base_url=get_api_url(), timeout=30.0, **kwargs)


def get_streaming_client(**kwargs: Any) -> httpx.Client:
    """Create an HTTP client for SSE streaming.

    Connect/write/pool timeouts are kept finite so a misconfigured host does
    not hang indefinitely before the stream even starts.  Read timeout is
    ``None`` because SSE streams are long-lived by design.
    """
    timeout = httpx.Timeout(connect=5.0, write=10.0, read=None, pool=5.0)
    return httpx.Client(base_url=get_api_url(), timeout=timeout, **kwargs)
