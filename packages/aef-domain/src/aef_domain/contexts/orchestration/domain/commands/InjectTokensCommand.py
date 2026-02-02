"""InjectTokensCommand - command to inject API tokens into workspace."""

from __future__ import annotations

from dataclasses import dataclass, field

from event_sourcing import Command

from aef_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    TokenType,
)


@dataclass
class InjectTokensCommand(Command):
    """Command to inject API tokens into workspace.

    Per ADR-022 (Secure Token Architecture):
    - Tokens are vended by TokenVendingService with short TTL
    - Tokens are injected via sidecar proxy (preferred)
    - Agent containers never hold raw API keys

    Attributes:
        workspace_id: Target workspace ID
        token_types: Types of tokens to inject
        ttl_seconds: Token validity duration
        scopes: Optional scope restrictions
    """

    workspace_id: str
    token_types: tuple[TokenType, ...] = (TokenType.ANTHROPIC,)
    ttl_seconds: int = 300  # 5 minutes default
    scopes: list[str] = field(default_factory=list)
