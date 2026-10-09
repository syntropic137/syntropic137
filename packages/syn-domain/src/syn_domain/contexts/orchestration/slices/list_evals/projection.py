"""Eval list and detail projection (#967).

One document per Eval, built from the Eval stream alone: name, Goal, Baseline,
tags, frozen and archived. It deliberately holds no run facts. An Eval does not
list its runs (each Execution records its Eval), and an execution's status
already lives in the execution list, which records ``eval_id``. So the run
count, the status tally and the member rows are read from there at query time,
filtered by ``eval_id`` in the store's query, and cannot disagree with the
Executions view or double-count a replayed event.

The one run fact the Eval stream DOES own is a run's score (``EvalRunScored``,
Evals v2). Each is kept as its own document, keyed by (eval, execution), so a
re-score overwrites the run's current score and history stays in the stream.
A score is read beside the run, never instead of it: an execution that is no
longer a member keeps its document, and the runs view simply never asks for it.

Pure and replay-safe: every handler overwrites the Eval's own document or one
score document, so replaying the stream any number of times yields the same
state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration._shared.execution_list_reads import ExecutionListReads
from syn_domain.contexts.orchestration._shared.tags import TagSet, replay_tag_edit
from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import Verdict
from syn_domain.contexts.orchestration.domain.events.EvalArchivedEvent import EvalArchivedEvent
from syn_domain.contexts.orchestration.domain.events.EvalCreatedEvent import (
    BaselineRepoPayload,
    EvalCreatedEvent,
)
from syn_domain.contexts.orchestration.domain.events.EvalFrozenEvent import EvalFrozenEvent
from syn_domain.contexts.orchestration.domain.events.EvalRunScoredEvent import (
    EvalRunScoredEvent,
)
from syn_domain.contexts.orchestration.domain.events.EvalUpdatedEvent import EvalUpdatedEvent
from syn_domain.contexts.orchestration.domain.read_models.eval_runs import EvalRunScore
from syn_domain.contexts.orchestration.domain.read_models.eval_summary import (
    EvalBaselineRepo,
    EvalDefinitionChange,
    EvalDetail,
    EvalRecord,
    EvalSummary,
)
from syn_domain.pagination import Page, ProjectionRecord
from syn_domain.projection_page import PageQuery, StatusOf, page_projection

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable
    from datetime import datetime

    from event_sourcing import ProjectionStore

    from syn_domain.contexts.orchestration.domain.events.EvalUpdatedEvent import (
        BaselineRepoPayload as UpdatedBaselineRepoPayload,
    )
    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
        WorkflowExecutionSummary,
    )


class EvalListProjection(AutoDispatchProjection):
    """Builds the eval list and eval detail read models from Eval events."""

    PROJECTION_NAME = "evals"
    SCORES = "eval_run_scores"
    VERSION = 3
    """2: run scores (``EvalRunScored``) in ``SCORES``.
    3: ``judge_model`` on scores; definition version and changes on records (#1788)."""

    def __init__(self, store: ProjectionStore):
        self._store = store
        self._runs = ExecutionListReads(store)

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    async def clear_all_data(self) -> None:
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)
            await self._store.delete_all(self.SCORES)

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
            definition_changes=(EvalDefinitionChange(definition_version=1, changed_at=created_at),),
        )
        await self._save(record)

    async def on_eval_updated(self, event_data: EvalUpdatedEvent) -> None:
        event = EvalUpdatedEvent.model_validate(event_data)
        record = await self._record(event.eval_id)
        if record is None:
            return
        tags = replay_tag_edit(record.tags, event.tags_added, added=True)
        tags = replay_tag_edit(tags, event.tags_removed, added=False)
        updated_at = event.updated_at.isoformat()
        changes = record.definition_changes
        redefines = event.goal is not None or event.baseline_repos is not None
        # A redelivered event carries the same time: it is not a second change.
        if redefines and not any(c.changed_at == updated_at for c in changes):
            version = changes[-1].definition_version + 1 if changes else 1
            changes = (
                *changes,
                EvalDefinitionChange(definition_version=version, changed_at=updated_at),
            )
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
                    "updated_at": updated_at,
                    "definition_changes": changes,
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

    async def on_eval_run_scored(self, event_data: EvalRunScoredEvent) -> None:
        event = EvalRunScoredEvent.model_validate(event_data)
        score = EvalRunScore(
            eval_id=event.eval_id,
            execution_id=event.execution_id,
            verdict=Verdict(event.verdict),
            score=event.score,
            evidence=event.evidence,
            scorer=event.scorer,
            scorer_version=event.scorer_version,
            scored_at=event.scored_at.isoformat(),
            judge_model=event.judge_model,
        )
        await self._store.save(
            self.SCORES,
            _score_key(event.eval_id, event.execution_id),
            score.model_dump(mode="json"),
        )

    async def scores(self, eval_id: str) -> dict[str, EvalRunScore]:
        """Every run's current score in the eval, by execution id, members or not."""
        documents = await self._store.query(self.SCORES, filters={"eval_id": eval_id})
        scores = (EvalRunScore.model_validate(document) for document in documents)
        return {score.execution_id: score for score in scores}

    async def scores_in(self, eval_ids: Collection[str]) -> dict[tuple[str, str], EvalRunScore]:
        """Every run's current score in each Eval given, by ``(eval_id, execution_id)``, in one read.

        What ``scores`` answers for each Eval, without a read per Eval (#1811).
        Filtered by Eval alone: also filtering by every member's execution id
        multiplies the filter by the size of the page for no fewer rows.
        """
        if not eval_ids:
            return {}
        documents = await self._store.query(self.SCORES, filters={"eval_id": sorted(set(eval_ids))})
        scores = (EvalRunScore.model_validate(document) for document in documents)
        return {(score.eval_id, score.execution_id): score for score in scores}

    async def score(self, eval_id: str, execution_id: str) -> EvalRunScore | None:
        """The run's current score in the eval, or None if it was never scored."""
        document = await self._store.get(self.SCORES, _score_key(eval_id, execution_id))
        return None if document is None else EvalRunScore.model_validate(document)

    async def scores_of(
        self, runs: Collection[tuple[str, str]]
    ) -> dict[tuple[str, str], EvalRunScore]:
        """The current score of each ``(eval_id, execution_id)`` run given, in one read.

        Runs never scored are omitted. Answers what ``score`` answers for each
        run, without a read per run.
        """
        if not runs:
            return {}
        documents = await self._store.query(
            self.SCORES,
            filters={
                "eval_id": sorted({eval_id for eval_id, _ in runs}),
                "execution_id": sorted({execution_id for _, execution_id in runs}),
            },
        )
        # The filter is the product of both id sets, so it can return a score
        # for a pair that was not asked about; keep only the runs given.
        wanted = set(runs)
        scores = (EvalRunScore.model_validate(document) for document in documents)
        return {
            key: score for score in scores if (key := (score.eval_id, score.execution_id)) in wanted
        }

    async def records(self, eval_ids: Collection[str]) -> dict[str, EvalRecord]:
        """Each Eval's own record, by id, in one read; ids not yet projected are omitted."""
        if not eval_ids:
            return {}
        documents = await self._store.query(
            self.PROJECTION_NAME, filters={"eval_id": sorted(set(eval_ids))}
        )
        return {record.eval_id: record for record in map(_from_document, documents)}

    async def record(self, eval_id: str) -> EvalRecord | None:
        """The Eval's own record (name, Goal, Baseline), without its runs."""
        return await self._record(eval_id)

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
        query = PageQuery(
            status=StatusOf.flag("archived", if_true="archived", if_false="active"),
            timestamp_field="created_at",
            contains_all={"tags": frozenset(tags or ())},
            search=search,
            search_fields=("eval_id", "name", "goal"),
            statuses=frozenset(statuses) if statuses else None,
            after=created_after,
            before=created_before,
            offset=offset,
            limit=limit,
        )
        records = await page_projection(
            self._store, self.PROJECTION_NAME, query, to_row=_from_document
        )
        tallies = await self._runs.run_tallies([record.eval_id for record in records.rows])
        return Page(
            rows=[
                EvalSummary(
                    record=record,
                    run_count=sum(tallies[record.eval_id].values()),
                    run_status_counts=tallies[record.eval_id],
                )
                for record in records.rows
            ],
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
        runs = await self.members(eval_id, statuses=run_statuses, offset=offset, limit=limit)
        return EvalDetail(record=record, runs=runs)

    async def members(
        self,
        eval_id: str,
        *,
        statuses: Collection[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> Page[WorkflowExecutionSummary]:
        """One page of the Eval's current member executions, newest first.

        Read from the execution list alone, so a run is listed as soon as its
        own stream is projected, even before the Eval's record catches up.
        """
        return await self._runs.page(eval_id=eval_id, statuses=statuses, offset=offset, limit=limit)

    async def members_of(
        self, eval_ids: Collection[str]
    ) -> dict[str, list[WorkflowExecutionSummary]]:
        """Every current member execution of each Eval given, in one read, unordered.

        A page of the eval list needs every run of every eval on it; asking
        ``members`` once per eval was a query per row (#1811).
        """
        return await self._runs.members_of(eval_ids)

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


def _score_key(eval_id: str, execution_id: str) -> str:
    # "/" is outside both id alphabets, so no two (eval, execution) pairs collide.
    return f"{eval_id}/{execution_id}"


def _from_document(document: ProjectionRecord) -> EvalRecord:
    return EvalRecord.model_validate(document)
