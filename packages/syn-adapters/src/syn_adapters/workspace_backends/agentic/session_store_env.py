"""Build the session-store contract injected into workspace containers.

The session-store capability ships inside the agentic-primitives workspace
image and activates purely from environment variables. Syntropic137's entire
job is to write those variables into the container environment at provision
time; there is no capture code on this side.

Opt-in, default OFF
-------------------
If no store URL is configured, :func:`build_session_store_env` returns an EMPTY
dict — not ``PROVIDER=none``, not empty values, nothing. With
``AGENTIC_SESSION_STORE_PROVIDER`` unset the capability is a complete no-op in
the container (no init, no doctor, no finalize), so a self-hoster with no
SeshMagic instance sees byte-identical behaviour to having no integration at
all. That guarantee is the point of this module and is covered by tests.

Partition safety
----------------
The capability HARD-FAILS the workspace if the partition is absolute or
contains ``..``. Identifiers reaching this module come from the orchestration
domain and are normally opaque ids, but they are sanitised here rather than
trusted: a workflow-supplied id must never be able to take down provisioning or
escape its partition prefix.

See ADR-021 (Isolated Workspace Architecture) for the surrounding container
lifecycle.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from syn_shared.env_constants import (
    ENV_AGENTIC_SESSION_STORE_AUTH,
    ENV_AGENTIC_SESSION_STORE_PARTITION,
    ENV_AGENTIC_SESSION_STORE_PROVIDER,
    ENV_AGENTIC_SESSION_STORE_SPOOL,
    ENV_AGENTIC_SESSION_STORE_TAGS,
    ENV_AGENTIC_SESSION_STORE_URL,
)

if TYPE_CHECKING:
    from syn_shared.settings.session_store import SessionStoreSettings

__all__ = [
    "TAG_EXECUTION_ID",
    "TAG_PHASE_ID",
    "TAG_SOURCE",
    "TAG_WORKFLOW_ID",
    "TAG_WORKSPACE_ID",
    "build_session_store_env",
    "sanitize_partition_segment",
]

# Tag keys are part of the join contract with the session store: a row in the
# store is matched back to a Syn137 execution by these keys. Declared once here
# so the store-side query and this producer cannot drift apart silently.
TAG_SOURCE = "source"
TAG_EXECUTION_ID = "execution_id"
TAG_WORKSPACE_ID = "workspace_id"
TAG_WORKFLOW_ID = "workflow_id"
TAG_PHASE_ID = "phase_id"

#: Value of the ``source`` tag. Lets the store distinguish Syn137-originated
#: sessions from sessions captured by any other agentic-primitives consumer.
SOURCE_SYNTROPIC137 = "syntropic137"

#: Substituted for any character that is not safe in a single path segment.
_UNSAFE_SEGMENT_CHARS = re.compile(r"[^A-Za-z0-9._-]")

#: Collapses ``..`` (and longer runs) so a segment can never traverse upward.
_DOT_RUN = re.compile(r"\.{2,}")

#: Placeholder for an identifier that sanitises down to nothing.
_EMPTY_SEGMENT = "unknown"

#: Tag values are comma-separated ``key:value`` pairs, so both delimiters and
#: surrounding whitespace must be stripped out of values.
_UNSAFE_TAG_CHARS = re.compile(r"[,:\s]+")


def sanitize_partition_segment(raw: str | None) -> str:
    """Make ``raw`` safe as one segment of a relative partition path.

    Guarantees the result is non-empty, contains no path separator, is not
    absolute, and cannot contain ``..``. The capability rejects the workspace
    outright on any of those, so this is a hard requirement rather than
    cosmetics.
    """
    if not raw:
        return _EMPTY_SEGMENT

    # Any separator (or other unsafe char) becomes "_", so "/etc" -> "_etc"
    # and the result can never be absolute.
    cleaned = _UNSAFE_SEGMENT_CHARS.sub("_", raw)
    # ".." -> "." so no segment can traverse upward.
    cleaned = _DOT_RUN.sub(".", cleaned)
    # A leading/trailing "." is either a hidden-file marker or the residue of a
    # collapsed traversal; neither is wanted in a partition segment.
    cleaned = cleaned.strip(".")

    return cleaned or _EMPTY_SEGMENT


def _sanitize_tag_value(raw: str) -> str:
    """Strip the ``,`` and ``:`` delimiters (and whitespace) out of a tag value."""
    return _UNSAFE_TAG_CHARS.sub("_", raw.strip()).strip("_")


def _build_partition(execution_id: str, workspace_id: str) -> str:
    """Relative ``<execution_id>/<workspace_id>`` partition path."""
    return "/".join(
        (
            sanitize_partition_segment(execution_id),
            sanitize_partition_segment(workspace_id),
        )
    )


def _build_tags(
    *,
    execution_id: str,
    workspace_id: str,
    workflow_id: str | None,
    phase_id: str | None,
) -> str:
    """Comma-separated ``key:value`` tags that join a store row to an execution.

    Optional context (workflow, phase) is emitted only when actually present on
    the isolation config, so a tag is never a lie about missing data.
    """
    pairs: list[tuple[str, str | None]] = [
        (TAG_SOURCE, SOURCE_SYNTROPIC137),
        (TAG_EXECUTION_ID, execution_id),
        (TAG_WORKSPACE_ID, workspace_id),
        (TAG_WORKFLOW_ID, workflow_id),
        (TAG_PHASE_ID, phase_id),
    ]

    rendered: list[str] = []
    for key, value in pairs:
        if not value:
            continue
        safe = _sanitize_tag_value(value)
        if safe:
            rendered.append(f"{key}:{safe}")
    return ",".join(rendered)


def build_session_store_env(
    settings: SessionStoreSettings,
    *,
    execution_id: str,
    workspace_id: str,
    workflow_id: str | None = None,
    phase_id: str | None = None,
) -> dict[str, str]:
    """Return the session-store variables for one workspace container.

    Returns an EMPTY dict when no store is configured. Callers must merge the
    result rather than branching, so the disabled path adds literally nothing to
    the container environment.

    The auth token is read from the settings object at this single point and
    written straight into the returned mapping. It is never logged, never put in
    an exception message, and never placed in a container label (labels are
    readable by anyone who can run ``docker inspect``).
    """
    if not settings.is_enabled:
        return {}

    # `is_enabled` already proved url is a non-empty string.
    url = settings.url or ""

    env = {
        ENV_AGENTIC_SESSION_STORE_PROVIDER: settings.provider,
        ENV_AGENTIC_SESSION_STORE_URL: url.strip(),
        ENV_AGENTIC_SESSION_STORE_SPOOL: settings.spool_dir,
        ENV_AGENTIC_SESSION_STORE_PARTITION: _build_partition(execution_id, workspace_id),
        ENV_AGENTIC_SESSION_STORE_TAGS: _build_tags(
            execution_id=execution_id,
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
        ),
    }

    # AUTH is always emitted when the store is on, even if the operator runs an
    # unauthenticated store: the capability treats an empty token as "no auth
    # header" rather than as a misconfiguration.
    env[ENV_AGENTIC_SESSION_STORE_AUTH] = settings.auth_value

    return env
