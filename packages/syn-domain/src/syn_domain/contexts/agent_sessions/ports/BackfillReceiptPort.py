"""Durable once-only materialization of legacy records without source IDs (#1398)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.read_models.legacy_evidence import (
        BackfillReceipt,
    )
    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
        RunIdentity,
    )


class BackfillReceiptConflict(Exception):
    """A concurrent materializer won. Re-read existing receipts and plan again."""


class BackfillReceiptPort(Protocol):
    async def existing(self, run: RunIdentity) -> tuple[BackfillReceipt, ...]:
        """All receipts for the run, in materialization order."""
        ...

    async def insert(self, run: RunIdentity, receipts: tuple[BackfillReceipt, ...]) -> None:
        """All or nothing. A reused fingerprint or snapshot ordinal raises a conflict."""
        ...
