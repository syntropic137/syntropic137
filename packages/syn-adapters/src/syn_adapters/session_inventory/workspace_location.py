"""Reconstruct storage identity from a durable pre-launch session fact."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import RunIdentity


class WorkspaceCaptureLocation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    volume_name: str
    partition: str
    envelope_dir: str


def workspace_capture_location(run: RunIdentity, session_id: str) -> WorkspaceCaptureLocation:
    """Versioned mapping; never derive it from transient container/workspace IDs."""
    if not session_id.strip() or "\x00" in session_id:
        raise ValueError("A persisted session identity is required")
    key = json.dumps(
        ["workspace-capture/1", run.source_instance_id, run.execution_id, session_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(key.encode()).hexdigest()
    return WorkspaceCaptureLocation(
        volume_name=f"syn-capture-{digest}",
        partition=digest,
        envelope_dir=f"/spool/.agentic-session-store/{digest}/envelopes",
    )
