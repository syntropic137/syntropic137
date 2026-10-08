"""Every shipped review phase reaches execution declaring ``requires_verdict`` (PC-116).

Through the same six hops as `delivers_repo_changes` (#1308), the event-store
JSON round trip included: a field the template event does not carry is lost
on the restart path only, and every in-process test stays green. True is the
value no dropped hop can produce - the default is False - so each review entry
fails if the declaration is lost anywhere between the YAML and
`ExecutablePhase`.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.test_1308_the_declaration_survives_to_execution import (
    _WORKFLOWS,
    _executable_phases,
)

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_ROUNDS = ("verify", "reverify", "reverify_2")
_REVIEWS = [(w, p) for w in ("sdlc/implement-v3", "sdlc/reverify-pr") for p in _ROUNDS]

#: Phases whose silence must still advance by order, so a change that declared
#: every phase would not satisfy the list above.
_NOT_REVIEWS = [
    ("sdlc/implement-v3", "implement"),
    ("sdlc/implement-v3", "fix"),
    ("sdlc/implement-v3", "fix_2"),
    ("sdlc/implement-v3", "finalize_pr"),
    ("sdlc/reverify-pr", "prepare"),
    ("sdlc/reverify-pr", "fix_2"),
    ("sdlc/reverify-pr", "finalize_pr"),
]


@pytest.mark.parametrize(("workflow", "phase_id"), _REVIEWS)
async def test_a_review_phase_reaches_execution_requiring_a_verdict(
    workflow: str, phase_id: str
) -> None:
    phases = await _executable_phases(_WORKFLOWS / workflow / "workflow.yaml")

    assert phase_id in phases, f"{workflow} no longer has a '{phase_id}' phase"
    assert phases[phase_id].requires_verdict is True


@pytest.mark.parametrize(("workflow", "phase_id"), _NOT_REVIEWS)
async def test_a_phase_that_judges_nothing_is_not_asked_for_a_verdict(
    workflow: str, phase_id: str
) -> None:
    phases = await _executable_phases(_WORKFLOWS / workflow / "workflow.yaml")

    assert phase_id in phases, f"{workflow} no longer has a '{phase_id}' phase"
    assert phases[phase_id].requires_verdict is False
