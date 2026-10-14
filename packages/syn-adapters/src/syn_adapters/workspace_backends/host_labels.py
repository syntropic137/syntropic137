"""The Docker labels that say which API host created a container (#1310 0.4).

Every workspace and sidecar container carries them, so a host can tell its own
containers from another host's, and the generation that created them from the
one now running. Nothing reads them yet: the reap is unchanged by this module.

- ``syn.host_id`` is ``SYN_HOST_ID`` if set, else this process's hostname.
  With the Run Queue on it also carries a suffix drawn once per process, so it
  is the Executor identity: never reused across a restart (ADR-072 D5).
- ``syn.host_generation`` is the image tag the API was built as
  (``SYN_BUILD_IMAGE_TAG``), or ``unknown`` for a build that stamped none.
"""

from __future__ import annotations

import functools
import os
import socket
from uuid import uuid4

from syn_shared.env_constants import ENV_BUILD_IMAGE_TAG
from syn_shared.settings import get_settings

LABEL_HOST_ID = "syn.host_id"
LABEL_HOST_GENERATION = "syn.host_generation"

#: Generation of a build that stamped no image tag (compose, dry-run). Always
#: written rather than omitted, so the label is present on every container.
UNKNOWN_GENERATION = "unknown"


@functools.cache
def _process_suffix() -> str:
    """Drawn once per process, so every container this process creates agrees."""
    return uuid4().hex[:12]


def executor_host_id() -> str:
    """This process's ``syn.host_id``; unique per process with the Run Queue on (D5)."""
    settings = get_settings()
    base = settings.syn_host_id or socket.gethostname()
    if not settings.execution.run_queue_enabled:
        return base
    return f"{base}.{_process_suffix()}"


def host_labels() -> dict[str, str]:
    """The host labels for a container this process is about to create."""
    image_tag = os.environ.get(ENV_BUILD_IMAGE_TAG, "").strip()
    return {
        LABEL_HOST_ID: executor_host_id(),
        LABEL_HOST_GENERATION: image_tag or UNKNOWN_GENERATION,
    }
