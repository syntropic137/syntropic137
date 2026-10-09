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
deliberately not `InMemoryProjectionStore` and not an `InMemoryAdapter`, and why
the in-memory fitness check exempts it by name, citing ADR-072 D8.

WHY THE PROJECTION TYPE IS PASSED IN. `ExecutionTodoProjection` lives in the
`execution_todo` slice, and a slice may not import another (VSA031). The
processor already receives its projection from the composition root rather
than importing it; the fold receives the projection's class the same way.

WHY SEEDING GOES THROUGH THE JOURNAL'S DISPATCH. `project_events` is the code
the journal runs after every save. Seeding through anything else would be a
second fold that agrees with the first only until one of them changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
    project_events,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from event_sourcing import ProjectionStore

    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        ExecutionRepository,
        TodoProjection,
    )

# The `ProjectionStore` protocol speaks in dicts, and the projection's record is
# one. Dicts exist only at that boundary: what the store holds is `_TodoRecord`.
type _Record = dict[str, Any]

_ITEM_FIELDS = frozenset({"execution_id", "action", "phase_id", "workspace_id", "session_id"})
_RECORD_FIELDS = frozenset({"execution_id", "items", "phase_progress"})


class ExecutionEventStream(Protocol):
    """Every domain event one execution's stream holds, in stream order."""

    async def read(self, execution_id: str) -> Sequence[object]: ...


class TodoProjectionType(Protocol):
    """The to-do projection's class, as the composition root hands it over.

    `ExecutionTodoProjection` satisfies it; the fold never imports that slice.
    """

    @property
    def PROJECTION_NAME(self) -> str: ...

    def __call__(self, store: ProjectionStore) -> TodoProjection: ...


def _optional_str(value: object, name: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"to-do item field {name} must be a string or null, not {value!r}")


def _exact_fields(data: _Record, expected: frozenset[str], what: str) -> None:
    # A field the store does not know would be dropped on the next read, and the
    # fold would quietly disagree with the shared projection. Refuse it instead.
    if set(data) != expected:
        raise ValueError(f"{what} has fields {sorted(data)}, expected {sorted(expected)}")


@dataclass(frozen=True)
class _TodoRecord:
    """One execution's to-do record, immutable all the way down.

    Every read hands out freshly built dicts, so nothing a caller does to what
    it got back, or to what it saved, reaches the record. Only a save does.
    """

    execution_id: str
    items: tuple[TodoItem, ...]
    phase_progress: tuple[tuple[str, int], ...]

    @classmethod
    def from_record(cls, data: _Record) -> _TodoRecord:
        _exact_fields(data, _RECORD_FIELDS, "to-do record")
        execution_id = data["execution_id"]
        items = data["items"]
        progress = data["phase_progress"]
        if not isinstance(execution_id, str):
            raise ValueError(f"to-do record execution_id must be a string, not {execution_id!r}")
        if not isinstance(items, list | tuple) or not isinstance(progress, dict):
            raise ValueError("to-do record needs a list of items and a phase_progress mapping")
        return cls(
            execution_id=execution_id,
            items=tuple(cls._item(item) for item in items),  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            phase_progress=tuple(cls._rank(p, r) for p, r in progress.items()),  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        )

    @staticmethod
    def _item(data: object) -> TodoItem:
        if not isinstance(data, dict):
            raise ValueError(f"to-do item must be a mapping, not {data!r}")
        item: _Record = data  # pyright: ignore[reportUnknownVariableType]
        _exact_fields(item, _ITEM_FIELDS, "to-do item")
        execution_id = item["execution_id"]
        if not isinstance(execution_id, str):
            raise ValueError(f"to-do item execution_id must be a string, not {execution_id!r}")
        return TodoItem(
            execution_id=execution_id,
            action=TodoAction(item["action"]),
            phase_id=_optional_str(item["phase_id"], "phase_id"),
            workspace_id=_optional_str(item["workspace_id"], "workspace_id"),
            session_id=_optional_str(item["session_id"], "session_id"),
        )

    @staticmethod
    def _rank(phase_id: object, rank: object) -> tuple[str, int]:
        if not isinstance(phase_id, str) or not isinstance(rank, int):
            raise ValueError(f"phase_progress must map phase ids to ranks, not {phase_id!r}")
        return phase_id, rank

    def to_record(self) -> _Record:
        return {
            "execution_id": self.execution_id,
            "items": [
                {
                    "execution_id": item.execution_id,
                    "action": item.action.value,
                    "phase_id": item.phase_id,
                    "workspace_id": item.workspace_id,
                    "session_id": item.session_id,
                }
                for item in self.items
            ],
            "phase_progress": dict(self.phase_progress),
        }


class RunTodoStore:
    """A `ProjectionStore` that holds one execution's to-do record and nothing else.

    Any read or write naming another projection or another execution raises:
    a run-scoped fold that touched a second record would no longer be one
    run's fold, and failing loudly is cheaper than finding out from a
    dashboard.
    """

    def __init__(self, projection_name: str, execution_id: str) -> None:
        self._projection_name = projection_name
        self._execution_id = execution_id
        self._record: _TodoRecord | None = None

    def _scope(self, projection: str, key: str | None = None) -> None:
        if projection != self._projection_name or key not in (None, self._execution_id):
            raise ValueError(
                f"RunTodoStore for execution {self._execution_id} holds only its own "
                f"{self._projection_name} record, not {projection}/{key}"
            )

    async def save(self, projection: str, key: str, data: _Record) -> None:
        self._scope(projection, key)
        self._record = _TodoRecord.from_record(data)

    async def get(self, projection: str, key: str) -> _Record | None:
        self._scope(projection, key)
        return None if self._record is None else self._record.to_record()

    async def get_all(self, projection: str) -> list[_Record]:
        self._scope(projection)
        return [] if self._record is None else [self._record.to_record()]

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

    projection: TodoProjection
    journal: ExecutionJournal

    @classmethod
    async def for_execution(
        cls,
        execution_id: str,
        repository: ExecutionRepository,
        events: ExecutionEventStream,
        projection_type: TodoProjectionType,
    ) -> RunScopedTodoFold:
        """The fold for `execution_id`, caught up with every event it has stored."""
        projection = projection_type(RunTodoStore(projection_type.PROJECTION_NAME, execution_id))
        await project_events(projection, await events.read(execution_id))
        return cls(projection=projection, journal=ExecutionJournal(repository, projection))
