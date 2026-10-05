"""Eval list and detail projection (#967).

One document per Eval, built from the Eval stream alone: name, Goal, Baseline,
tags, frozen and archived. It deliberately holds no run facts. An Eval does not
list its runs (each Execution records its Eval), and an execution's status
already lives in the execution list, which records ``eval_id``. So the run
count, the status tally and the member rows are read from there at query time,
filtered by ``eval_id`` in the store's query, and cannot disagree with the
Executions view or double-count a replayed event.

Pure and replay-safe: every handler overwrites the Eval's own document, so
replaying the stream any number of times yields the same state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration._shared.tags import TagSet, replay_tag_edit
from syn_domain.contexts.orchestration.domain.events.EvalArchivedEvent import EvalArchivedEvent
from syn_domain.contexts.orchestration.domain.events.EvalCreatedEvent import (
    BaselineRepoPayload,
    EvalCreatedEvent,
)
from syn_domain.contexts.orchestration.domain.events.EvalFrozenEvent import EvalFrozenEvent
from syn_domain.contexts.orchestration.domain.events.EvalUpdatedEvent import EvalUpdatedEvent
from syn_domain.contexts.orchestration.domain.read_models.eval_summary import (
    EvalBaselineRepo,
    EvalDetail,
    EvalRecord,
    EvalSummary,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)
from syn_domain.pagination import Page, matches_search
from syn_domain.projection_scan import paginate_projection

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping
    from datetime import datetime

    from event_sourcing import ProjectionStore

    from syn_domain.contexts.orchestration.domain.events.EvalUpdatedEvent import (
        BaselineRepoPayload as UpdatedBaselineRepoPayload,
    )

#: Every field ``page``'s predicates read; see ``paginate_projection``.
_PAGE_FIELDS = ("eval_id", "name", "goal", "tags", "archived", "created_at")


class EvalListProjection(AutoDispatchProjection):
    """Builds the eval list and eval detail read models from Eval events."""

    PROJECTION_NAME = "evals"
    VERSION = 1

    def __init__(self, store: ProjectionStore):
        self._store = store
        self._runs = WorkflowExecutionListProjection(store)

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    async def clear_all_data(self) -> None:
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)

    async def on_eval_created(self, event_data: EvalCreatedEvent) -> None:
        event = EvalCreatedEvent.model_validate(event_data)
        created_at = event.created_at.isoformat()
        record = EvalRecord(
            eval_id=event.eval_id,
            name=event.name,
            goal=event.goal,
            starting_workflow_id=event.starting_workflow_id,
            baseline_repos=_baseline(event.baseline_repos),
            tags=TagSet.recorded(event.tags).values,
            frozen=False,
            archived=False,
            created_at=created_at,
            updated_at=created_at,
        )
        await self._save(record)

    async def on_eval_updated(self, event_data: EvalUpdatedEvent) -> None:
        event = EvalUpdatedEvent.model_validate(event_data)
        record = await self._record(event.eval_id)
        if record is None:
            return
        tags = replay_tag_edit(record.tags, event.tags_added, added=True)
        tags = replay_tag_edit(tags, event.tags_removed, added=False)
        await self._save(
            record.model_copy(
                update={
                    "name": record.name if event.name is None else event.name,
                    "goal": record.goal if event.goal is None else event.goal,
                    "baseline_repos": (
                        record.baseline_repos
                        if event.baseline_repos is None
                        else _baseline(event.baseline_repos)
                    ),
                    "tags": tuple(tags),
                    "updated_at": event.updated_at.isoformat(),
                }
            )
        )

    async def on_eval_frozen(self, event_data: EvalFrozenEvent) -> None:
        event = EvalFrozenEvent.model_validate(event_data)
        record = await self._record(event.eval_id)
        if record is not None:
            await self._save(
                record.model_copy(
                    update={"frozen": True, "updated_at": event.frozen_at.isoformat()}
                )
            )

    async def on_eval_archived(self, event_data: EvalArchivedEvent) -> None:
        event = EvalArchivedEvent.model_validate(event_data)
        record = await self._record(event.eval_id)
        if record is not None:
            await self._save(
                record.model_copy(
                    update={"archived": True, "updated_at": event.archived_at.isoformat()}
                )
            )

    async def page(
        self,
        *,
        statuses: Collection[str] | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        search: str | None = None,
        tags: Collection[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> Page[EvalSummary]:
        """One page of Evals, newest first, each with its run count and tally.

        ``statuses`` selects ``active`` and/or ``archived``; ``status_counts``
        tallies both whatever is selected. ``search`` matches the id, name and
        Goal; ``tags`` keeps Evals carrying every tag given, normalised.
        """
        required = frozenset(tags or ())

        def base(record: Mapping[str, object]) -> bool:
            stored = record.get("tags")
            if required and not (isinstance(stored, list) and required.issubset(stored)):
                return False
            return matches_search(
                search, record.get("eval_id"), record.get("name"), record.get("goal")
            )

        records = await paginate_projection(
            self._store,
            self.PROJECTION_NAME,
            fields=_PAGE_FIELDS,
            filters=None,
            order_by=None,
            full_read=lambda: self._store.get_all(self.PROJECTION_NAME),
            base_predicate=base,
            status_of=lambda r: "archived" if r.get("archived") else "active",
            statuses=statuses,
            timestamp_of=lambda r: r.get("created_at"),
            after=created_after,
            before=created_before,
            to_row=_from_document,
            offset=offset,
            limit=limit,
        )
        rows = []
        for record in records.rows:
            tally = await self._runs.page(eval_id=record.eval_id, limit=0)
            rows.append(
                EvalSummary(
                    record=record, run_count=tally.total, run_status_counts=tally.status_counts
                )
            )
        return Page(
            rows=rows,
            total=records.total,
            status_counts=records.status_counts,
            excluded_undated=records.excluded_undated,
        )

    async def detail(
        self,
        eval_id: str,
        *,
        run_statuses: Collection[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> EvalDetail | None:
        """The Eval, its Baseline, and one page of its current member executions."""
        record = await self._record(eval_id)
        if record is None:
            return None
        runs = await self._runs.page(
            eval_id=eval_id, statuses=run_statuses, offset=offset, limit=limit
        )
        return EvalDetail(record=record, runs=runs)

    async def _record(self, eval_id: str) -> EvalRecord | None:
        document = await self._store.get(self.PROJECTION_NAME, eval_id)
        return None if document is None else _from_document(document)

    async def _save(self, record: EvalRecord) -> None:
        await self._store.save(self.PROJECTION_NAME, record.eval_id, record.model_dump(mode="json"))


def _baseline(
    repos: Iterable[BaselineRepoPayload | UpdatedBaselineRepoPayload],
) -> tuple[EvalBaselineRepo, ...]:
    return tuple(
        EvalBaselineRepo(
            owner=repo.repository.owner,
            name=repo.repository.name,
            requested_ref=repo.requested_ref,
            commit_sha=repo.commit_sha,
        )
        for repo in repos
    )


def _from_document(document: Mapping[str, object]) -> EvalRecord:
    return EvalRecord.model_validate(document)
