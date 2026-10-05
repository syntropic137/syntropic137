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

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import (  # noqa: TC001 - pydantic field type
    EvalId,
)

if TYPE_CHECKING:
    # Annotation only: a dataclass never evaluates it, and importing it at
    # runtime would cycle through the ports package back into the commands.
    from syn_domain.contexts.orchestration._shared.repository_baseline import (
        RepositoryBaseline,
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
            return LaunchEval(str(self.eval_id), EvalSelection.EXPLICIT)
        if self.ordinary:
            return LaunchEval(None, EvalSelection.ORDINARY)
        if workflow_default:
            return LaunchEval(workflow_default, EvalSelection.WORKFLOW_DEFAULT)
        return LaunchEval(None, EvalSelection.NONE)


@dataclass(frozen=True)
class LaunchEval:
    """A resolved launch: the eval joined (or None), how it was chosen, and its baseline.

    ``baseline`` is empty until the eval admits the launch: only the eval's
    frozen baseline is ever recorded, so it is read back from the aggregate
    that froze it (``eval_admission.admit_launch``), never taken from a request.
    """

    eval_id: str | None
    selection: EvalSelection
    baseline: tuple[RepositoryBaseline, ...] = ()

    def admitted(self, baseline: tuple[RepositoryBaseline, ...]) -> LaunchEval:
        """This launch, carrying the baseline its eval froze when it admitted it."""
        return replace(self, baseline=baseline)
