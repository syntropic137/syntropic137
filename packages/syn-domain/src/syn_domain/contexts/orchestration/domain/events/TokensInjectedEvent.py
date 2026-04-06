"""TokensInjectedEvent - tokens have been injected into workspace."""

from __future__ import annotations

from datetime import datetime

from event_sourcing import DomainEvent, event


@event("TokensInjected", "v1")
class TokensInjectedEvent(DomainEvent):
    """Event emitted when tokens are injected into workspace.

    Records token injection for audit trail and TTL tracking.
    Note: Never includes actual token values.
    """

    # Workspace identity
    workspace_id: str

    # Token info (types only, never values)
    token_types: list[str]  # ["anthropic", "github"]
    ttl_seconds: int

    # Injection method
    injected_via: str  # "sidecar", "env_var", "file"

    # Timing
    injected_at: datetime
