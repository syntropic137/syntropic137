"""Which eval a launch joins (evals plan, #967).

Answered at dispatch, once, in this order:

1. an eval the launch names explicitly;
2. otherwise the workflow's ``default_eval_id``;
3. unless the launch asks for an ordinary run, which suppresses the default.

The answer is recorded on the execution's start event, so changing a workflow's
default later never reclassifies a run that already started.

Pure values only: commands import this, so it must not reach the aggregates.
Whether the eval can take the run is ``eval_admission``'s question.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, model_validator

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import (
    EvalId,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts._shared.repository_ref import RepositoryRef

    # Annotation only: a dataclass never evaluates it, and importing it at
    # runtime would cycle through the ports package back into the commands.
    from syn_domain.contexts.orchestration._shared.repository_baseline import (
        RepositoryBaseline,
    )


class RepositoryOutsideBaselineError(ValueError):
    """A run in an eval names a repository the eval's frozen baseline does not pin."""

    def __init__(self, eval_id: EvalId, slugs: Sequence[str]) -> None:
        self.eval_id = eval_id
        self.slugs = tuple(slugs)
        super().__init__(
            f"Eval {eval_id} has no baseline for {', '.join(self.slugs)}: every run of an "
            "eval starts from its frozen baseline, so it cannot check out a live head"
        )


class EvalSelection(StrEnum):
    """How a launch arrived at its eval. Recorded on the start event."""

    EXPLICIT = "explicit"
    """The launch named the eval."""
    WORKFLOW_DEFAULT = "workflow_default"
    """The launch named none and the workflow had a default."""
    ORDINARY = "ordinary"
    """The launch asked for an ordinary run, suppressing any default."""
    NONE = "none"
    """The launch named none and the workflow had no default."""


class EvalChoice(BaseModel):
    """What a launch request says about evals. The empty choice defers to the workflow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    eval_id: EvalId | None = None
    ordinary: bool = False

    @model_validator(mode="after")
    def _one_or_the_other(self) -> Self:
        if self.ordinary and self.eval_id is not None:
            msg = "a launch cannot name an eval and ask for an ordinary run"
            raise ValueError(msg)
        return self

    def resolve(self, workflow_default: str | None) -> LaunchEval:
        """The eval this launch joins, given the workflow's default at dispatch."""
        if self.eval_id is not None:
            return LaunchEval(self.eval_id, EvalSelection.EXPLICIT)
        if self.ordinary:
            return LaunchEval(None, EvalSelection.ORDINARY)
        if workflow_default:
            return LaunchEval(EvalId.recorded(workflow_default), EvalSelection.WORKFLOW_DEFAULT)
        return LaunchEval(None, EvalSelection.NONE)


@dataclass(frozen=True)
class LaunchEval:
    """A resolved launch: the eval joined (or None), how it was chosen, and its baseline.

    ``baseline`` is empty until the eval admits the launch: only the eval's
    frozen baseline is ever recorded, so it is read back from the aggregate
    that froze it (``eval_admission.admit_launch``), never taken from a request.
    """

    eval_id: EvalId | None
    selection: EvalSelection
    baseline: tuple[RepositoryBaseline, ...] = ()

    def __post_init__(self) -> None:
        # A dataclass checks no types, so a bare string would ride the command
        # unvalidated; refuse it here and the event boundary alone sees a str.
        if self.eval_id is not None and not isinstance(self.eval_id, EvalId):
            msg = f"LaunchEval.eval_id must be an EvalId, not {type(self.eval_id).__name__}"
            raise TypeError(msg)

    def admitted(self, baseline: tuple[RepositoryBaseline, ...]) -> LaunchEval:
        """This launch, carrying the baseline its eval froze when it admitted it."""
        return replace(self, baseline=baseline)

    def refuse_unpinned(self, repos: Sequence[RepositoryRef]) -> None:
        """Refuse a run in an eval whose repositories its baseline does not all pin.

        Every run of an eval starts from the same code, so a repository the
        baseline does not name has no commit to start from; checking out its
        live head would make the run incomparable with its siblings. A run in
        no eval has no baseline to honour and passes.
        """
        if self.eval_id is None:
            return
        pinned = {pin.repository.slug for pin in self.baseline}
        unpinned = [repo.slug for repo in repos if repo.slug not in pinned]
        if unpinned:
            raise RepositoryOutsideBaselineError(self.eval_id, unpinned)
