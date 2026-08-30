"""Adapters for the delegate import ledger (#933, #936).

Mirrors ``syn_adapters.dedup``: the port lives in the domain, the durable and
test implementations live here. Postgres is the only durable backend, because
the mark has to stay consistent with the cost rows in ``agent_events`` - a
ledger in a different store can disagree with the spend it is supposed to
describe, and the disagreement is invisible.
"""

from syn_adapters.import_ledger.memory_ledger import InMemoryImportLedger
from syn_adapters.import_ledger.postgres_ledger import PostgresImportLedger

__all__ = ["InMemoryImportLedger", "PostgresImportLedger"]
