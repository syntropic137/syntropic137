"""Apply host-owned local capture storage to a controlled workflow workspace."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentic_isolation import MountConfig

from syn_domain.contexts.agent_sessions import RunIdentity
from syn_shared.env_constants import (
    ENV_AGENTIC_SESSION_STORE_PARTITION,
    ENV_AGENTIC_SESSION_STORE_PROVIDER,
    ENV_AGENTIC_SESSION_STORE_SPOOL,
)

from .workspace_location import WorkspaceCaptureLocation, workspace_capture_location

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
    )


def apply_workspace_capture(
    config: IsolationConfig,
    source_instance_id: str,
    environment: dict[str, str],
) -> list[MountConfig]:
    """No session identity means this is not a registered workflow launch."""
    location = apply_capture_environment(config, source_instance_id, environment)
    if location is None:
        return []
    return [MountConfig(location.volume_name, "/spool", kind="volume")]


def apply_capture_environment(
    config: IsolationConfig,
    source_instance_id: str,
    environment: dict[str, str],
) -> WorkspaceCaptureLocation | None:
    """Point the session-store capability at ``/spool`` and this session's partition.

    The whole capture strategy for a sandbox spool (#2161): the spool is the
    sandbox's own ``/spool`` directory, so nothing is mounted. Docker adds the
    named volume on top (:func:`apply_workspace_capture`). Both use the same
    partition, so recovery reads either from the row alone.
    """
    if config.capture_session_id is None:
        return None
    location = workspace_capture_location(
        RunIdentity(source_instance_id=source_instance_id, execution_id=config.execution_id),
        config.capture_session_id,
    )
    environment.update(
        {
            ENV_AGENTIC_SESSION_STORE_PROVIDER: "local",
            ENV_AGENTIC_SESSION_STORE_SPOOL: "/spool",
            ENV_AGENTIC_SESSION_STORE_PARTITION: location.partition,
            "AGENTIC_SESSION_STORE_EXPORTER_BIN": "/usr/local/bin/apss-session-exporter",
        }
    )
    capabilities = environment.get("AGENTIC_CAPABILITIES", "memory session-store").split()
    environment["AGENTIC_CAPABILITIES"] = " ".join(dict.fromkeys([*capabilities, "session-store"]))
    return location
