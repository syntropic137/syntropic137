"""The delegate import ledger's wiring (#933, #936).

Split from `_wiring.py`: one durable store, chosen by ADR-060 priority with no
Redis tier and no in-memory fallback in production. Nothing here imports from
`_wiring.py`, so the dependency runs one way.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import ImportLedgerPort

logger = logging.getLogger(__name__)

_import_ledger_singleton: ImportLedgerPort | None = None


def get_import_ledger() -> ImportLedgerPort:
    """Return the process-wide delegate import ledger (#933, #936).

    A singleton because `get_execution_processor()` builds a NEW processor per
    dispatch. A fresh Postgres adapter each time would re-issue CREATE TABLE on
    every execution, and a fresh in-memory one would forget the mark between
    phases of a single execution - which is precisely the cross-phase recount
    #936 is about, reintroduced by the wiring rather than the logic.

    Postgres or nothing. Unlike dedup there is no Redis tier: the mark says how
    much of a session has already been CHARGED, and it has to stay consistent
    with the cost rows in `agent_events`. A ledger in a different store can
    disagree with the spend it describes, and nothing in the system would
    report the disagreement - it would just quietly bill wrong.

    ADR-060: never fall back to in-memory in production. Losing the mark on
    restart silently reverts to double-billing delegates (#936), which is the
    overcount failure mode that nobody reports because it just looks expensive.
    """
    global _import_ledger_singleton
    if _import_ledger_singleton is not None:
        return _import_ledger_singleton

    from syn_shared.settings import get_settings

    settings = get_settings()

    if settings.uses_in_memory_stores:
        from syn_adapters.import_ledger import InMemoryImportLedger

        _import_ledger_singleton = InMemoryImportLedger()
        return _import_ledger_singleton

    if settings.syn_observability_db_url:
        from syn_api._wiring_db import get_shared_db_pool

        pool = get_shared_db_pool()
        if pool is not None:
            from syn_adapters.import_ledger import PostgresImportLedger

            logger.info("Delegate import ledger using Postgres (ADR-060)")
            _import_ledger_singleton = PostgresImportLedger(pool)  # type: ignore[arg-type]  # asyncpg.Pool vs AsyncConnectionPool
            return _import_ledger_singleton

    raise RuntimeError(
        "No durable delegate import ledger available. Configure "
        "SYN_OBSERVABILITY_DB_URL for production. Without it, delegate cost is "
        "double-billed across phases (#936) and across a crash (#933). "
        "See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md)."
    )
