"""EvalAggregate invariants, decided in memory (evals plan, #967).

Store-level behaviour - replay, concurrency, create-only writes - is tested
in the slices that persist the aggregate.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.repository_baseline import RepositoryBaseline
from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain.aggregate_eval import (
    DuplicateBaselineRepositoryError,
    EvalAggregate,
    EvalAlreadyExistsError,
    EvalArchivedError,
    EvalFrozenError,
    EvalId,
    EvalNotCreatedError,
    EvalRuleError,
    Goal,
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

pytestmark = pytest.mark.unit

_ID = EvalId("eval-1")


def _pin(slug: str, sha: str = "a" * 40, ref: str = "main") -> RepositoryBaseline:
    return RepositoryBaseline(
        repository=RepositoryRef.from_slug(slug), requested_ref=ref, commit_sha=sha
    )


def _created(*baseline: RepositoryBaseline) -> EvalAggregate:
    aggregate = EvalAggregate()
    aggregate.create(
        CreateEvalCommand(
            eval_id=_ID,
            name="Refactor quality",
            goal=Goal("Does the agent keep tests green?"),
            baseline_repos=baseline or (_pin("acme/api"),),
            tags=TagSet(["nightly"]),
        )
    )
    return aggregate


def _frozen() -> EvalAggregate:
    aggregate = _created()
    aggregate.freeze(FreezeEvalCommand(eval_id=_ID))
    return aggregate


def _archived() -> EvalAggregate:
    aggregate = _created()
    aggregate.archive(ArchiveEvalCommand(eval_id=_ID, archived_by="ops"))
    return aggregate


def _event_types(aggregate: EvalAggregate) -> list[str]:
    return [e.event.event_type for e in aggregate.get_uncommitted_events()]


class TestCreate:
    def test_records_the_definition(self) -> None:
        aggregate = _created(_pin("acme/web", "b" * 40), _pin("acme/api"))
        assert _event_types(aggregate) == ["EvalCreated"]
        assert aggregate.name == "Refactor quality"
        assert aggregate.tags == TagSet(["nightly"])
        # Canonical order: by repository, so the same baseline compares equal.
        assert [b.repository.slug for b in aggregate.baseline_repos] == ["acme/api", "acme/web"]
        assert not aggregate.is_frozen
        assert not aggregate.is_archived

    def test_refuses_a_second_create(self) -> None:
        aggregate = _created()
        with pytest.raises(EvalAlreadyExistsError):
            aggregate.create(CreateEvalCommand(eval_id=_ID, name="x", goal=Goal("y")))

    def test_refuses_one_repository_twice(self) -> None:
        with pytest.raises(DuplicateBaselineRepositoryError, match="acme/api"):
            _created(_pin("acme/api"), _pin("ACME/api", "b" * 40, "dev"))


class TestValueObjects:
    @pytest.mark.parametrize("sha", ["abc1234", "A" * 40, "g" * 40, "a" * 41])
    def test_baseline_refuses_anything_but_a_full_lowercase_sha(self, sha: str) -> None:
        with pytest.raises(ValidationError, match="commit_sha"):
            _pin("acme/api", sha)

    def test_baseline_accepts_sha256_object_ids(self) -> None:
        assert _pin("acme/api", "c" * 64).commit_sha == "c" * 64

    def test_goal_is_trimmed_and_never_empty(self) -> None:
        assert str(Goal("  measure it  ")) == "measure it"
        with pytest.raises(ValidationError):
            Goal("   ")

    def test_eval_id_refuses_path_characters(self) -> None:
        with pytest.raises(ValidationError):
            EvalId("../etc")


class TestFrozen:
    def test_freeze_is_idempotent(self) -> None:
        aggregate = _frozen()
        aggregate.mark_events_as_committed()
        aggregate.freeze(FreezeEvalCommand(eval_id=_ID))
        assert aggregate.get_uncommitted_events() == []
        assert aggregate.is_frozen

    @pytest.mark.parametrize(
        ("command", "field"),
        [
            (UpdateEvalCommand(eval_id=_ID, goal=Goal("Something else")), "goal"),
            (
                UpdateEvalCommand(eval_id=_ID, baseline_repos=(_pin("acme/api", "b" * 40),)),
                "baseline",
            ),
            (UpdateEvalCommand(eval_id=_ID, baseline_repos=()), "baseline"),
        ],
    )
    def test_refuses_goal_and_baseline_changes(
        self, command: UpdateEvalCommand, field: str
    ) -> None:
        aggregate = _frozen()
        aggregate.mark_events_as_committed()
        with pytest.raises(EvalFrozenError, match=field):
            aggregate.update(command)
        assert aggregate.get_uncommitted_events() == []

    def test_a_refused_update_changes_nothing_else_either(self) -> None:
        aggregate = _frozen()
        aggregate.mark_events_as_committed()
        with pytest.raises(EvalFrozenError):
            aggregate.update(UpdateEvalCommand(eval_id=_ID, name="Renamed", goal=Goal("New")))
        assert aggregate.name == "Refactor quality"

    def test_resending_the_recorded_goal_and_baseline_is_not_a_change(self) -> None:
        aggregate = _frozen()
        aggregate.mark_events_as_committed()
        aggregate.update(
            UpdateEvalCommand(
                eval_id=_ID,
                goal=Goal("Does the agent keep tests green?"),
                baseline_repos=(_pin("acme/api"),),
            )
        )
        assert aggregate.get_uncommitted_events() == []

    def test_name_and_tags_stay_editable(self) -> None:
        aggregate = _frozen()
        aggregate.mark_events_as_committed()
        aggregate.update(
            UpdateEvalCommand(
                eval_id=_ID,
                name="Renamed",
                add_tags=TagSet(["weekly"]),
                remove_tags=TagSet(["nightly"]),
            )
        )
        assert _event_types(aggregate) == ["EvalUpdated"]
        assert aggregate.name == "Renamed"
        assert aggregate.tags == TagSet(["weekly"])


class TestArchived:
    def test_refuses_update(self) -> None:
        with pytest.raises(EvalArchivedError, match="updated"):
            _archived().update(UpdateEvalCommand(eval_id=_ID, name="Renamed"))

    def test_refuses_freeze(self) -> None:
        with pytest.raises(EvalArchivedError, match="frozen"):
            _archived().freeze(FreezeEvalCommand(eval_id=_ID))

    def test_archive_is_idempotent(self) -> None:
        aggregate = _archived()
        aggregate.mark_events_as_committed()
        aggregate.archive(ArchiveEvalCommand(eval_id=_ID))
        assert aggregate.get_uncommitted_events() == []

    def test_a_frozen_eval_can_be_archived(self) -> None:
        aggregate = _frozen()
        aggregate.archive(ArchiveEvalCommand(eval_id=_ID))
        assert aggregate.is_archived
        assert aggregate.is_frozen


class TestUpdate:
    def test_no_change_records_nothing(self) -> None:
        aggregate = _created()
        aggregate.mark_events_as_committed()
        aggregate.update(
            UpdateEvalCommand(eval_id=_ID, name="Refactor quality", add_tags=TagSet(["nightly"]))
        )
        assert aggregate.get_uncommitted_events() == []

    def test_records_only_what_differs(self) -> None:
        aggregate = _created()
        aggregate.mark_events_as_committed()
        aggregate.update(UpdateEvalCommand(eval_id=_ID, name="Refactor quality", goal=Goal("New")))
        event = aggregate.get_uncommitted_events()[0].event
        assert event.model_dump(include={"name", "goal"}) == {"name": None, "goal": "New"}

    def test_refuses_the_same_tag_added_and_removed(self) -> None:
        aggregate = _created()
        with pytest.raises(EvalRuleError, match="same tag"):
            aggregate.update(
                UpdateEvalCommand(eval_id=_ID, add_tags=TagSet(["x"]), remove_tags=TagSet(["x"]))
            )

    def test_unfrozen_baseline_can_be_replaced(self) -> None:
        aggregate = _created()
        aggregate.update(
            UpdateEvalCommand(eval_id=_ID, baseline_repos=(_pin("acme/web", "b" * 40),))
        )
        assert [b.repository.slug for b in aggregate.baseline_repos] == ["acme/web"]


@pytest.mark.parametrize(
    "command",
    [
        UpdateEvalCommand(eval_id=_ID, name="x"),
        FreezeEvalCommand(eval_id=_ID),
        ArchiveEvalCommand(eval_id=_ID),
    ],
)
def test_every_command_but_create_needs_an_existing_eval(
    command: UpdateEvalCommand | FreezeEvalCommand | ArchiveEvalCommand,
) -> None:
    aggregate = EvalAggregate()
    with pytest.raises(EvalNotCreatedError):
        aggregate._handle_command(command)  # pyright: ignore[reportPrivateUsage]
