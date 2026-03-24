"""Token vending and spend tracking for secure agent execution.

This package provides:
- TokenVendingService: Issues short-lived, scoped tokens
- SpendTracker: Tracks and limits API spend per execution
- Budget management for Claude API cost control

Architecture:
- Tokens are stored in Redis with TTL
- Spend is tracked atomically per execution
- Alerts fire on budget threshold breaches

See Also:
    - docs/adrs/ADR-022-secure-token-architecture.md
    - docs/deployment/claude-api-security.md
"""

from syn_tokens.models import ScopedToken, SpendBudget, TokenScope, TokenType, WorkflowType
from syn_tokens.singletons import get_spend_tracker, get_token_vending_service
from syn_tokens.spend import SpendTracker
from syn_tokens.vending import TokenVendingService

__all__ = [
    "ScopedToken",
    "SpendBudget",
    "SpendTracker",
    "TokenScope",
    "TokenType",
    "TokenVendingService",
    "WorkflowType",
    "get_spend_tracker",
    "get_token_vending_service",
]
