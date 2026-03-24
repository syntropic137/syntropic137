"""Line-reading helper for agentic event stream adapter.

Extracted from stream_helpers.py to reduce module cognitive complexity.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.agentic.stream_helpers import _is_stream_timed_out

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


async def read_lines(
    proc: asyncio.subprocess.Process,
    stream_timeout: float | None,
    start_time: float,
) -> AsyncIterator[str]:
    """Read and yield decoded lines from process stdout."""
    while True:
        if _is_stream_timed_out(stream_timeout, start_time):
            break

        if proc.stdout is None:
            break

        try:
            line_bytes = await asyncio.wait_for(
                proc.stdout.readline(), timeout=1.0,
            )
        except TimeoutError:
            if proc.returncode is not None:
                break
            continue

        if not line_bytes:
            break

        line = line_bytes.decode("utf-8", errors="replace").rstrip("\n\r")
        if line:
            yield line
