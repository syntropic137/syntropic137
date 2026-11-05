"""The version of the orchestration events' shapes (ADR-072 D9).

Admission writes it as a run's ``writer_epoch`` so an Executor claims only work
whose events it can load. Bump it whenever an orchestration event's schema
changes: ``ci/fitness/event_sourcing/test_orchestration_event_schema_snapshot.py``
fails a schema that differs from this epoch's snapshot, and
``just check-event-compat`` fails a payload the previous release cannot read
unless this was bumped. The append-side ``reader_epoch`` check is not built yet
(#1310).
"""

from __future__ import annotations

from typing import Final

ORCHESTRATION_EVENT_EPOCH: Final = 9
