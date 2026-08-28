"""System-wide canonical usage totals (issue #932)."""

from syn_domain.contexts.agent_sessions.slices.canonical_totals.query_service import (
    CanonicalTotals,
    CanonicalUsageQueryService,
)

__all__ = ["CanonicalTotals", "CanonicalUsageQueryService"]
