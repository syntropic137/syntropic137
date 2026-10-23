"""Compose healthcheck for docker-create-guard: exit 0 when the guard accepts connections.

Run BY PATH, not with ``-m``:

    python -I /app/packages/syn-adapters/src/syn_adapters/docker_create_guard/healthcheck.py

``-m`` imports the ``syn_adapters`` package first, whose ``__init__`` pulls in
the event store and object storage clients. Under the guard's CPU limit that
took over 20 s, so every probe hit its 5 s timeout and the guard never went
healthy. This file imports the standard library only (pinned by a test), so a
probe costs one interpreter start.
"""

from __future__ import annotations

import os
import socket
import sys

DEFAULT_PORT = 2375


def healthcheck(port: int, *, timeout: float = 3.0) -> bool:
    """True when the guard is accepting connections on ``port``."""
    try:
        socket.create_connection(("127.0.0.1", port), timeout).close()
    except OSError:
        return False
    return True


def main() -> int:
    port = int(os.environ.get("SYN_DOCKER_CREATE_GUARD_PORT", str(DEFAULT_PORT)))
    return 0 if healthcheck(port) else 1


if __name__ == "__main__":
    sys.exit(main())
