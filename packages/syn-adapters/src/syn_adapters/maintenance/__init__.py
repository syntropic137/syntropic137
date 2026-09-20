"""Adapters for maintenance mode, the execution admission gate (#1387).

Mirrors ``syn_adapters.dedup``: the port lives in the domain shared kernel,
the durable and test implementations live here. Postgres first, Redis as the
fallback, in-memory for tests only - the ADR-060 chain, for the ADR-060 reason:
a maintenance flag lost on restart re-opens admission in the middle of the
deploy it was set for, and nothing reports that it happened.
"""

from syn_adapters.maintenance.event_store_announcer import EventStoreAdmissionAnnouncer
from syn_adapters.maintenance.memory_maintenance import InMemoryMaintenanceAdapter
from syn_adapters.maintenance.postgres_maintenance import PostgresMaintenanceAdapter
from syn_adapters.maintenance.redis_maintenance import RedisMaintenanceAdapter

__all__ = [
    "EventStoreAdmissionAnnouncer",
    "InMemoryMaintenanceAdapter",
    "PostgresMaintenanceAdapter",
    "RedisMaintenanceAdapter",
]
