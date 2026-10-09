"""One run's own to-do list, folded from its own events (ADR-072 D8, #1310 item 1.4).

WHY A RUN DOES NOT READ THE SHARED TO-DO LIST. The shared `execution_todo`
projection is one record per execution in a store every process can write: the
processor's in-process sync and the coordinator subscription both fold into it,
which is why `ExecutionTodoProjection` carries a class-level lock and a
monotonic merge (its module docstring). A lock in one process does nothing for
a writer in another. A run that folds into a store only it can see has exactly
one writer, so that whole class of race does not arise for it, whichever host
claims the run.

WHY THIS IS NOT AN IN-MEMORY ADAPTER (ADR-060). An in-memory adapter holds
state that exists nowhere else, and losing it on restart loses work; that is
what `InMemoryProjectionStore` refuses production over. `RunTodoStore` holds a
cache of durable state: it is created empty at every claim, seeded wholly from
the execution's stored events, and discarded with the run. Throw it away at any
point and `for_execution` rebuilds the same record. It is the "in-process
synchronous projection" the architecture notes prescribe, which is why it is
deliberately not `InMemoryProjectionStore`, not an `InMemoryAdapter`, and named
outside the in-memory fitness check's patterns.

WHY SEEDING GOES THROUGH THE JOURNAL'S DISPATCH. `project_events` is the code
the journal runs after every save. Seeding through anything else would be a
second fold that agrees with the first only until one of them changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
    project_events,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        ExecutionRepository,
    )

# The `ProjectionStore` protocol speaks in dicts, and the projection's record is
# one. Named once so the shape is declared in one place.
type _Record = dict[str, Any]


class ExecutionEventStream(Protocol):
    """Every domain event one execution's stream holds, in stream order."""

    async def read(self, execution_id: str) -> Sequence[object]: ...


class RunTodoStore:
    """A `ProjectionStore` that holds one execution's to-do record and nothing else.

    Any read or write naming another projection or another execution raises:
    a run-scoped fold that touched a second record would no longer be one
    run's fold, and failing loudly is cheaper than finding out from a
    dashboard.
    """

    def __init__(self, execution_id: str) -> None:
        self._execution_id = execution_id
        self._record: _Record | None = None

    def _scope(self, projection: str, key: str | None = None) -> None:
        if projection != ExecutionTodoProjection.PROJECTION_NAME or key not in (
            None,
            self._execution_id,
        ):
            raise ValueError(
                f"RunTodoStore for execution {self._execution_id} holds only its own "
                f"{ExecutionTodoProjection.PROJECTION_NAME} record, not {projection}/{key}"
            )

    async def save(self, projection: str, key: str, data: _Record) -> None:
        self._scope(projection, key)
        self._record = dict(data)

    async def get(self, projection: str, key: str) -> _Record | None:
        self._scope(projection, key)
        return None if self._record is None else dict(self._record)

    async def get_all(self, projection: str) -> list[_Record]:
        self._scope(projection)
        return [] if self._record is None else [dict(self._record)]

    async def delete(self, projection: str, key: str) -> None:
        self._scope(projection, key)
        self._record = None

    async def delete_all(self, projection: str) -> None:
        self._scope(projection)
        self._record = None

    async def query(
        self,
        projection: str,
        filters: _Record | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[_Record]:
        # At most one record, so ordering is moot; filters still apply.
        del order_by
        records = [
            r
            for r in await self.get_all(projection)
            if all(r.get(field) == value for field, value in (filters or {}).items())
        ]
        return records[offset:] if limit is None else records[offset : offset + limit]

    async def get_by_prefix(self, projection: str, prefix: str) -> list[tuple[str, _Record]]:
        return [
            (self._execution_id, record)
            for record in await self.get_all(projection)
            if self._execution_id.startswith(prefix)
        ]


@dataclass(frozen=True)
class RunScopedTodoFold:
    """A run's private to-do list and the journal that keeps it current.

    `projection` answers `get_pending` for this execution only; `journal`
    records the run's saves and folds them into that same projection. Both
    are created together at a claim and dropped together when the run ends.
    """

    projection: ExecutionTodoProjection
    journal: ExecutionJournal

    @classmethod
    async def for_execution(
        cls,
        execution_id: str,
        repository: ExecutionRepository,
        events: ExecutionEventStream,
    ) -> RunScopedTodoFold:
        """The fold for `execution_id`, caught up with every event it has stored."""
        projection = ExecutionTodoProjection(store=RunTodoStore(execution_id))
        await project_events(projection, await events.read(execution_id))
        return cls(projection=projection, journal=ExecutionJournal(repository, projection))
