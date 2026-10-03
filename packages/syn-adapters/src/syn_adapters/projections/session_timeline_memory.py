"""In-memory stand-in for the TimescaleDB session timeline (test/offline only).

Production keeps a session's operations in the ``agent_events`` hypertable:
the write path records observations through ``AgentEventStore`` and
``SessionToolsProjection`` reads them back with SQL. Test and offline runs have
no such table, so that read answers ``[]`` for a reason that has nothing to do
with the code under test - which is how #1034 stayed invisible to a green suite
for as long as it did.

This object is both ends of that lane, so a write is readable in a test exactly
as it is in production. It is deliberately ONE object and not a writer beside a
reader: two halves that can be wired to different stores is the defect, not the
design.

Conversion goes through ``to_operation``, the same dispatch the SQL path uses,
so a test can never pass against a friendlier rendering than production's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from syn_adapters.in_memory import assert_test_only
from syn_adapters.projections.session_tools import (
    GIT_EVENT_TYPES,
    SUBAGENT_TOOL_NAMES,
    TIMELINE_EXCLUDE,
    SessionToolsProjection,
    ToolOperation,
)
from syn_adapters.projections.session_tools_dispatch import resolve_durations, to_operation

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
        ObservationType,
    )


@dataclass(frozen=True)
class _Observed:
    """One recorded observation, held as the SQL row would have held it."""

    session_id: str
    event_type: str
    time: datetime
    data: dict[str, Any]


class InMemorySessionTimeline(SessionToolsProjection):
    """A session timeline held in memory, satisfying both sides of the lane.

    Subclasses ``SessionToolsProjection`` rather than standing beside it so
    every existing reader - session detail, the events routes, observability -
    keeps working unchanged, including the ``query`` surface below that still
    needs a pool and so still answers empty here.
    """

    def __init__(self) -> None:
        assert_test_only()
        super().__init__(pool=None)
        # ACKNOWLEDGED in-memory state (ADR-060): telemetry for one test or
        # offline process. The durable equivalent is the agent_events
        # hypertable, and the assertion above is why this cannot be reached
        # anywhere it would be expected to survive a restart.
        self._observed: list[_Observed] = []

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: dict[str, Any],
        execution_id: str | None = None,  # noqa: ARG002
        phase_id: str | None = None,  # noqa: ARG002
        workspace_id: str | None = None,  # noqa: ARG002
    ) -> None:
        """Append one observation. Satisfies ``SessionObservationPort``.

        The correlation ids are accepted and dropped: ``get`` filters on the
        session alone, exactly as the SQL behind it does, so keeping them would
        only invite a reader production cannot support.
        """
        self._observed.append(
            _Observed(
                session_id=session_id,
                event_type=str(observation_type),
                time=datetime.now(UTC),
                data=dict(data),
            )
        )

    async def get(self, session_id: str) -> list[ToolOperation]:
        """Every timeline operation recorded for this session, oldest first."""
        converted = (
            to_operation(o.time, o.data, o.event_type, SUBAGENT_TOOL_NAMES, GIT_EVENT_TYPES)
            for o in self._observed
            if o.session_id == session_id and o.event_type not in TIMELINE_EXCLUDE
        )
        # The SAME multi-row pass the SQL reader applies (#1064). A call's
        # duration is a property of the PAIR of rows - nothing in a harness
        # stream carries a per-item timestamp - so a converter that sees one
        # row can never produce it. Without this the two readers answer
        # differently for identical rows, and the in-memory one is what tests
        # and offline runs see, so the divergence hides exactly where it would
        # be caught.
        return resolve_durations([op for op in converted if op is not None])


@lru_cache(maxsize=1)
def get_in_memory_session_timeline() -> InMemorySessionTimeline:
    """The one timeline the write path and the read path share.

    Shared deliberately. A test that records through its own instance and reads
    through another proves only that two objects exist.
    """
    return InMemorySessionTimeline()


def reset_in_memory_session_timeline() -> None:
    """Forget every recorded observation (between tests)."""
    get_in_memory_session_timeline.cache_clear()
