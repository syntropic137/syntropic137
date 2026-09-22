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

from .workspace_location import workspace_capture_location

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
    if config.capture_session_id is None:
        return []
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
    return [MountConfig(location.volume_name, "/spool", kind="volume")]
