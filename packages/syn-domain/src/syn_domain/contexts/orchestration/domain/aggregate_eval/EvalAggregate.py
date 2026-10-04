"""Eval aggregate root (evals plan, #967).

Location: orchestration/domain/aggregate_eval/ (per ADR-020).

An eval is an experiment: a goal, measured by runs that all start from the
same pinned repository commits. This aggregate owns the experiment's
definition - name, goal, optional starting workflow, baseline, tags - and two
one-way switches:

- **frozen**: the goal and baseline can no longer change. Launch admission
  freezes an eval before it admits the first run, through ``FreezeEval`` and a
  persisted ``EvalFrozen``, so a concurrent baseline edit loses on the stream
  version instead of slipping past a lagging read model. Name and tags stay
  editable: they describe the experiment, they are not part of it.
- **archived**: the eval is retired. It refuses edits and freezing, stays
  readable, and keeps the runs it already has.

Runs are NOT recorded here. An execution owns its own eval membership, so this
stream does not grow with every run and attaching one is a single write.

The aggregate never resolves a ref: every ``RepositoryBaseline`` it receives
already carries a full commit sha, resolved by the slice handler through
``RevisionResolverPort``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain.aggregate_eval.errors import (
    DuplicateBaselineRepositoryError,
    EvalAlreadyExistsError,
    EvalArchivedError,
    EvalFrozenError,
    EvalNotCreatedError,
    EvalRuleError,
)
from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import (
    EvalId,
    Goal,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.orchestration._shared.repository_baseline import (
        RepositoryBaseline,
    )
    from syn_domain.contexts.orchestration.domain.commands.ArchiveEvalCommand import (
        ArchiveEvalCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.CreateEvalCommand import (
        CreateEvalCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.FreezeEvalCommand import (
        FreezeEvalCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.UpdateEvalCommand import (
        UpdateEvalCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.EvalArchivedEvent import (
        EvalArchivedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.EvalCreatedEvent import (
        EvalCreatedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.EvalFrozenEvent import (
        EvalFrozenEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.EvalUpdatedEvent import (
        EvalUpdatedEvent,
    )


def _canonical_baseline(
    baseline: Iterable[RepositoryBaseline],
) -> tuple[RepositoryBaseline, ...]:
    """One spelling per baseline: ordered by repository, each repository once.

    Ordering makes "the same baseline submitted in another order" equal to the
    recorded one, so re-sending it to a frozen eval is not mistaken for a change.
    """
    ordered = tuple(sorted(baseline, key=lambda b: b.repository.slug.lower()))
    counts = Counter(b.repository.slug.lower() for b in ordered)
    repeated = sorted(slug for slug, n in counts.items() if n > 1)
    if repeated:
        raise DuplicateBaselineRepositoryError(repeated)
    return ordered


def _requested(baseline: Iterable[RepositoryBaseline]) -> frozenset[tuple[RepositoryRef, str]]:
    return frozenset((b.repository, b.requested_ref) for b in baseline)


@dataclass(frozen=True)
class _EvalChange:
    """What an UpdateEval would actually change. ``None`` / empty is no change."""

    name: str | None
    goal: Goal | None
    baseline: tuple[RepositoryBaseline, ...] | None
    tags_added: TagSet
    tags_removed: TagSet

    @property
    def frozen_fields(self) -> list[str]:
        """The fields this change touches that freezing fixes."""
        touched = [("goal", self.goal), ("baseline", self.baseline)]
        return [field for field, value in touched if value is not None]

    def __bool__(self) -> bool:
        return bool(
            self.name is not None or self.frozen_fields or self.tags_added or self.tags_removed
        )


@aggregate("Eval")
class EvalAggregate(AggregateRoot["EvalCreatedEvent"]):
    """Eval aggregate root. Command handlers decide; event handlers record."""

    _aggregate_type: str

    def __init__(self) -> None:
        super().__init__()
        self._name: str | None = None
        self._goal: Goal | None = None
        self._starting_workflow_id: str | None = None
        self._baseline: tuple[RepositoryBaseline, ...] = ()
        self._tags: TagSet = TagSet()
        self._is_frozen: bool = False
        self._is_archived: bool = False
        self._created_at: datetime | None = None
        self._updated_at: datetime | None = None
        self._frozen_at: datetime | None = None
        self._archived_at: datetime | None = None

    def get_aggregate_type(self) -> str:
        return self._aggregate_type

    # =========================================================================
    # READ SURFACE
    # =========================================================================

    @property
    def eval_id(self) -> EvalId | None:
        return None if self.id is None else EvalId.recorded(str(self.id))

    @property
    def name(self) -> str | None:
        return self._name

    @property
    def goal(self) -> Goal | None:
        return self._goal

    @property
    def starting_workflow_id(self) -> str | None:
        return self._starting_workflow_id

    @property
    def baseline_repos(self) -> tuple[RepositoryBaseline, ...]:
        return self._baseline

    @property
    def tags(self) -> TagSet:
        return self._tags

    @property
    def is_frozen(self) -> bool:
        return self._is_frozen

    @property
    def is_archived(self) -> bool:
        return self._is_archived

    @property
    def created_at(self) -> datetime | None:
        return self._created_at

    @property
    def updated_at(self) -> datetime | None:
        return self._updated_at

    @property
    def frozen_at(self) -> datetime | None:
        return self._frozen_at

    @property
    def archived_at(self) -> datetime | None:
        return self._archived_at

    def was_created_by(self, command: CreateEvalCommand) -> bool:
        """Whether ``command`` is a retry of the create that made this eval.

        Baselines compare by repository and REQUESTED ref, not by sha: a retry
        arriving after its branch moved resolves to a newer commit, but it is
        still the same request, and the eval keeps the commit it first pinned.
        """
        return (
            self.id is not None
            and self._name == command.name
            and self._goal == command.goal
            and self._starting_workflow_id == command.starting_workflow_id
            and self._tags == command.tags
            and _requested(self._baseline) == _requested(command.baseline_repos)
        )

    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================

    @command_handler("CreateEvalCommand")
    def create(self, command: CreateEvalCommand) -> None:
        from syn_domain.contexts.orchestration.domain.events.EvalCreatedEvent import (
            EvalCreatedEvent,
        )

        if self.id is not None:
            raise EvalAlreadyExistsError(str(self.id))
        baseline = _canonical_baseline(command.baseline_repos)

        self._initialize(command.aggregate_id)
        self._apply(
            EvalCreatedEvent(
                eval_id=command.aggregate_id,
                name=command.name,
                goal=str(command.goal),
                starting_workflow_id=command.starting_workflow_id,
                baseline_repos=list(baseline),
                tags=list(command.tags),
                created_at=datetime.now(UTC),
            )
        )

    @command_handler("UpdateEvalCommand")
    def update(self, command: UpdateEvalCommand) -> None:
        """Apply the parts of ``command`` that differ. Nothing differs, no event."""
        from syn_domain.contexts.orchestration.domain.events.EvalUpdatedEvent import (
            EvalUpdatedEvent,
        )

        self._require_open("updated")
        change = self._change_from(command)
        if self._is_frozen and change.frozen_fields:
            raise EvalFrozenError(str(self.id), change.frozen_fields)
        if not change:
            return

        self._apply(
            EvalUpdatedEvent(
                eval_id=str(self.id),
                name=change.name,
                goal=None if change.goal is None else str(change.goal),
                baseline_repos=None if change.baseline is None else list(change.baseline),
                tags_added=list(change.tags_added),
                tags_removed=list(change.tags_removed),
                updated_at=datetime.now(UTC),
            )
        )

    @command_handler("FreezeEvalCommand")
    def freeze(self, _command: FreezeEvalCommand) -> None:
        """Fix the goal and baseline. Already frozen: nothing to record."""
        from syn_domain.contexts.orchestration.domain.events.EvalFrozenEvent import (
            EvalFrozenEvent,
        )

        self._require_open("frozen")
        if self._is_frozen:
            return
        self._apply(EvalFrozenEvent(eval_id=str(self.id), frozen_at=datetime.now(UTC)))

    @command_handler("ArchiveEvalCommand")
    def archive(self, command: ArchiveEvalCommand) -> None:
        """Retire the eval. Already archived: nothing to record."""
        from syn_domain.contexts.orchestration.domain.events.EvalArchivedEvent import (
            EvalArchivedEvent,
        )

        if self.id is None:
            raise EvalNotCreatedError
        if self._is_archived:
            return
        self._apply(
            EvalArchivedEvent(
                eval_id=str(self.id),
                archived_by=command.archived_by,
                archived_at=datetime.now(UTC),
            )
        )

    def _require_open(self, action: str) -> None:
        if self.id is None:
            raise EvalNotCreatedError
        if self._is_archived:
            raise EvalArchivedError(str(self.id), action)

    def _change_from(self, command: UpdateEvalCommand) -> _EvalChange:
        """Reduce ``command`` to what it would change, refusing an impossible edit."""
        overlap = command.add_tags.intersection(command.remove_tags)
        if overlap:
            msg = f"cannot add and remove the same tag(s) at once: {', '.join(overlap)}"
            raise EvalRuleError(msg)
        # Remove first so a full set can swap a tag in one edit; the union
        # then enforces MAX_TAGS against what the eval would actually carry.
        self._tags.difference(command.remove_tags).union(command.add_tags)

        baseline = None
        if command.baseline_repos is not None:
            baseline = _canonical_baseline(command.baseline_repos)
        return _EvalChange(
            name=command.name if command.name not in (None, self._name) else None,
            goal=command.goal if command.goal not in (None, self._goal) else None,
            baseline=baseline if baseline not in (None, self._baseline) else None,
            tags_added=command.add_tags.difference(self._tags),
            tags_removed=command.remove_tags.intersection(self._tags),
        )

    # =========================================================================
    # EVENT SOURCING HANDLERS - pure state changes, replayed on load
    # =========================================================================

    @event_sourcing_handler("EvalCreated")
    def on_eval_created(self, event: EvalCreatedEvent) -> None:
        self._name = event.name
        self._goal = Goal.recorded(event.goal)
        self._starting_workflow_id = event.starting_workflow_id
        self._baseline = tuple(event.baseline_repos)
        self._tags = TagSet.recorded(event.tags)
        self._created_at = event.created_at
        self._updated_at = event.created_at

    @event_sourcing_handler("EvalUpdated")
    def on_eval_updated(self, event: EvalUpdatedEvent) -> None:
        if event.name is not None:
            self._name = event.name
        if event.goal is not None:
            self._goal = Goal.recorded(event.goal)
        if event.baseline_repos is not None:
            self._baseline = tuple(event.baseline_repos)
        kept = self._tags.difference(TagSet.recorded(event.tags_removed))
        self._tags = TagSet.recorded([*kept, *event.tags_added])
        self._updated_at = event.updated_at

    @event_sourcing_handler("EvalFrozen")
    def on_eval_frozen(self, event: EvalFrozenEvent) -> None:
        self._is_frozen = True
        self._frozen_at = event.frozen_at

    @event_sourcing_handler("EvalArchived")
    def on_eval_archived(self, event: EvalArchivedEvent) -> None:
        self._is_archived = True
        self._archived_at = event.archived_at
