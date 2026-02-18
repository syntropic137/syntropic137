"""Shared asyncio bridge for CLI commands.

All CLI commands are sync (Typer requirement). This module provides
a single helper to run async API calls from sync command handlers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine  # noqa: TC003 — used in runtime signature
from typing import Any


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine synchronously.

    Handles the case where an event loop may already be running
    (e.g. inside Jupyter or nested async contexts).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()

    return asyncio.run(coro)
