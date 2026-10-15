"""The workspace runtime, translated across the agentic-workspace seam.

Syntropic137 owns the knob (`SYN_WORKSPACE_RUNTIME`, a syn_shared enum, since
syn_shared cannot import agentic_isolation). agentic-workspace owns everything
about what a runtime IS on a Docker host: which alias, which binary, what auto
mode picks. This module only translates between the two enums, in both
directions, and reads back the answer the provider's resolver recorded. It
detects nothing.

Both matches end in `assert_never`, so a runtime added on either side fails
pyright at the pin bump instead of silently mapping to something else.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, assert_never

from agentic_isolation import WorkspaceRuntime as AwRuntime

from syn_domain.contexts.orchestration import IsolationRuntime
from syn_shared.settings.workspace import WorkspaceRuntime

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["isolation_runtime_from_metadata", "to_aw_runtime"]

logger = logging.getLogger(__name__)

#: The keys agentic-workspace's Docker provider writes into `Workspace.metadata`
#: from the `ResolvedRuntime` it launched the container with.
_REQUESTED_KEY = "runtime_requested"
_EFFECTIVE_KEY = "runtime_effective"
_AUTO = "auto"


def to_aw_runtime(runtime: WorkspaceRuntime | None) -> AwRuntime | None:
    """The `SecurityConfig.runtime` for an operator's setting. None stays auto."""
    match runtime:
        case None:
            return None
        case WorkspaceRuntime.RUNC:
            return AwRuntime.RUNC
        case WorkspaceRuntime.GVISOR:
            return AwRuntime.GVISOR
        case WorkspaceRuntime.KATA:
            return AwRuntime.KATA
        case WorkspaceRuntime.SYSBOX:
            return AwRuntime.SYSBOX
        case _:
            assert_never(runtime)


def _from_aw_runtime(runtime: AwRuntime) -> WorkspaceRuntime:
    match runtime:
        case AwRuntime.RUNC:
            return WorkspaceRuntime.RUNC
        case AwRuntime.GVISOR:
            return WorkspaceRuntime.GVISOR
        case AwRuntime.KATA:
            return WorkspaceRuntime.KATA
        case AwRuntime.SYSBOX:
            return WorkspaceRuntime.SYSBOX
        case _:
            assert_never(runtime)


def isolation_runtime_from_metadata(metadata: Mapping[str, str]) -> IsolationRuntime | None:
    """The runtime the provider's resolver chose, or None if it recorded none.

    The values were written by agentic-workspace from its own enum, so they
    parse back into it. One that does not is a contract break between the pin
    and this code: it is logged and nothing is recorded, never guessed at. It
    does not fail the workspace, because this is telemetry and the container
    already runs under whatever the provider chose.
    """
    effective = metadata.get(_EFFECTIVE_KEY)
    if effective is None:
        return None
    requested = metadata.get(_REQUESTED_KEY, _AUTO)
    try:
        return IsolationRuntime(
            requested=None if requested == _AUTO else _from_aw_runtime(AwRuntime(requested)),
            effective=_from_aw_runtime(AwRuntime(effective)),
        )
    except ValueError:
        logger.warning(
            "Provider recorded a runtime this build does not know "
            "(runtime_requested=%r, runtime_effective=%r); not recording it",
            requested,
            effective,
        )
        return None
