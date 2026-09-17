"""Git hooks syntropic137 installs into a workspace at provision time.

## Why this exists here rather than only in the image

The workspace image is supposed to carry these. It does for the ``claude-cli``
provider, and it does NOT for ``omni-agent``, whose Dockerfile omits the
``COPY scripts/git-hooks/`` on the reasoning that the hooks belong to the
provider that owns the directory and that the entrypoint "skips a source
directory that does not exist, so omitting them is a supported subtraction, not
a breakage" (``providers/workspaces/omni-agent/Dockerfile:24-28``).

The ownership claim is true. The consequence claim is not: operator attribution
is not harness-specific, so the subtraction silently removed a cross-cutting
capability. It went unnoticed from 2026-05-10, when the hook landed, until
2026-09-10, when a real commit on a real deployment was inspected and found to
carry no trailer. Tracked as AgentParadise/agentic-primitives#401.

Waiting for that fix would mean waiting for a submodule merge, an image build,
promotion to the protected ``release`` channel, and a ``PINNED_DIGESTS`` bump -
the delivery path AGENTS.md warns about. Installing the hook at provision time
makes attribution work on **every** image, including images built before the
hook existed, which is the property actually wanted.

## Drift

``prepare-commit-msg`` here is a byte-for-byte MIRROR of the submodule's copy,
not a fork. ``test_attribution_hook_matches_submodule`` fails if they diverge,
so there is one source of truth and a gate that says so out loud. When #401
lands and every supported image carries the hook, this module can be deleted;
until then it is the only thing that makes the feature real.
"""

from __future__ import annotations

from importlib import resources
from pathlib import PurePosixPath

#: Where the workspace's ``core.hooksPath`` points. Set by the image entrypoint,
#: which composes this directory from its own hook sources; injecting into it
#: means the hook is found by exactly the mechanism the image already uses.
WORKSPACE_HOOKS_DIR = PurePosixPath("/home/agent/.git-hooks")

HOOK_FILENAME = "prepare-commit-msg"


def attribution_hook_source() -> bytes:
    """The hook's bytes, read from the package rather than the filesystem.

    Read as a package resource so it works from an installed wheel inside the
    API container, where no source tree exists.
    """
    return resources.files(__package__).joinpath(HOOK_FILENAME).read_bytes()
