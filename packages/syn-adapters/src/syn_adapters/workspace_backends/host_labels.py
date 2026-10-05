"""Which host created this container? The labels that answer it.

Every workspace and sidecar container is stamped with the host that created it
(``syn.host_id``) and the build that host was running (``syn.host_generation``),
so a container can be attributed to its creator from ``docker inspect`` alone
(#1310, hot-upgrade plan item 0.4). Both container builders take their labels
from here, so the two cannot disagree about what a host is.

``syn.host_id`` is configuration: ``SYN_HOST_ID``, defaulting to the container
hostname. ``syn.host_generation`` is NOT: it is the image tag stamped into the
image at build time (``SYN_BUILD_IMAGE_TAG``, see ``syn_api.build_info`` for why
that is read from the environment rather than from settings). An unstamped
build has no generation and says so with an empty value, never a placeholder
that could be mistaken for a real tag.
"""

from __future__ import annotations

import os

from syn_shared.settings import get_settings

LABEL_HOST_ID = "syn.host_id"
LABEL_HOST_GENERATION = "syn.host_generation"

#: Stamped by the image build; the same variable ``syn_api.build_info`` reads.
ENV_IMAGE_TAG = "SYN_BUILD_IMAGE_TAG"


def host_labels() -> dict[str, str]:
    """Labels identifying the host creating a container, keyed by label name."""
    return {
        LABEL_HOST_ID: get_settings().syn_host_id,
        LABEL_HOST_GENERATION: os.environ.get(ENV_IMAGE_TAG, ""),
    }
