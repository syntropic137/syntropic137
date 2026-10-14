"""The version of the orchestration events' shapes (ADR-072 D9).

Admission writes it as a run's ``writer_epoch`` so an Executor claims only work
whose events it can load. Bump it whenever an orchestration event's schema
changes. The fitness function that fails an unbumped schema change, and the
append-side ``reader_epoch`` check, are not built yet (#1310 Phase 1).
"""

from __future__ import annotations

from typing import Final

ORCHESTRATION_EVENT_EPOCH: Final = 1
