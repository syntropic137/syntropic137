"""Read-only acquisition of historical run evidence from existing sources (#1398).

Implementations normalize through existing typed readers and the harness
extraction port. They never parse vendor formats here, never call a model and
never write pricing, billing or ledger state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.read_models.legacy_evidence import (
        HistoricalAcquisition,
    )
    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
        RunIdentity,
    )


class HistoricalAcquisitionQuotaExceeded(Exception):
    """A source exceeded its bound. Report it; never backfill a truncated history."""


class HistoricalEvidenceSourcePort(Protocol):
    async def acquire(self, run: RunIdentity) -> HistoricalAcquisition:
        """Every eligible execution-scoped record, or raise. Order is not meaningful."""
        ...
