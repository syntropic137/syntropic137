"""No workflow phase deletes `.mutations/` before trusted mutation evidence (#2028).

A red `mutations-not-merged` check says the PR still tracks its mutation
patches. Fix phases read that as a defect and deleted the patches before the
trusted `mutation-evidence.yml` run had passed on the head, leaving a workspace
rerun as the only evidence (#2011, #2014). Briefs saying "do not delete" were
not enough, so the rule lives in the prompts themselves.

These read each prompt as `POST /workflows` installs it, which is what the agent
receives, not the markdown file the YAML points at.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)

pytestmark = pytest.mark.unit

_WORKFLOWS = Path(__file__).resolve().parents[2] / "workflows"

#: The workflows whose phases push to, or certify, a PR branch.
_PR_WORKFLOWS = (
    "sdlc/implement",
    "sdlc/implement-v3",
    "sdlc/implement-v4-precheck",
    "sdlc/reverify-pr",
    "custom/bake-opus",
    "custom/bake-haiku",
    "custom/bake-sonnet",
)

#: The workflows whose verifiers sort open items into precheck classes.
_PRECHECK_WORKFLOWS = ("sdlc/implement-v4-precheck",)

#: Phases that push to a PR branch that may carry `.mutations/`.
_PUSHERS = frozenset({"implement", "prepare", "fix", "fix_2"})

#: The rule every verifier treats as overriding: a red check on this SHA blocks.
_RED_BLOCKS = "**Failed on this SHA:** it IS a blocker"

_NEVER_DELETE = "**Never delete, move or rewrite anything under `.mutations/`**"
_NOT_A_BLOCKER = (
    "The one exception is `Mutation Patches Not Merged` (`mutations-not-merged`)."
    " It fails because the branch still tracks `.mutations/`"
)
_ORCHESTRATOR_EVIDENCE = (
    "A red `Mutation Patches Not Merged` check (`mutations-not-merged`) is in this"
    " class too, and is never `REPAIRABLE`"
)

#: `CI Success` goes red with `mutations-not-merged`; it is the same evidence
#: only when that is its sole failed prerequisite.
_AGGREGATE_ONLY = (
    "When `mutations-not-merged` is the only one that failed, `CI Success` is the"
    " same evidence: hand both off together under that heading, never to a fix phase."
)
_AGGREGATE_MIXED = (
    "When any other prerequisite also failed, that failure is a blocker as usual."
)
_AGGREGATE_PRECHECK = (
    "A red `CI Success` is the same class when `mutations-not-merged` is the only"
    " prerequisite that failed"
)


def _prompts(workflow: str) -> dict[str, str]:
    """Each installed phase's prompt, whitespace folded, keyed by phase id."""
    definition = WorkflowDefinition.from_file(_WORKFLOWS / workflow / "workflow.yaml")
    command = build_command_from_definition(definition)
    return {p.phase_id: re.sub(r"\s+", " ", p.prompt_template or "") for p in command.phases}


@pytest.mark.parametrize("workflow", _PR_WORKFLOWS)
def test_every_phase_that_pushes_never_deletes_mutation_patches(workflow: str) -> None:
    prompts = _prompts(workflow)
    pushers = prompts.keys() & _PUSHERS
    assert pushers, f"{workflow} has none of {sorted(_PUSHERS)}"
    for phase_id in sorted(pushers):
        assert _NEVER_DELETE in prompts[phase_id], f"{workflow}/{phase_id}"


@pytest.mark.parametrize("workflow", _PR_WORKFLOWS)
def test_no_verifier_makes_a_red_mutations_check_a_blocker(workflow: str) -> None:
    prompts = _prompts(workflow)
    verifiers = [pid for pid, text in prompts.items() if _RED_BLOCKS in text]
    assert verifiers, f"{workflow} has no verifier"
    for phase_id in verifiers:
        text = prompts[phase_id]
        assert _NOT_A_BLOCKER in text, f"{workflow}/{phase_id}"
        assert text.index(_NOT_A_BLOCKER) > text.index(_RED_BLOCKS), (
            f"{workflow}/{phase_id}: the exception must qualify the rule it overrides"
        )


@pytest.mark.parametrize("workflow", _PR_WORKFLOWS)
def test_the_aggregate_check_is_evidence_only_when_it_is_the_sole_failure(
    workflow: str,
) -> None:
    prompts = _prompts(workflow)
    verifiers = [pid for pid, text in prompts.items() if _RED_BLOCKS in text]
    assert verifiers, f"{workflow} has no verifier"
    for phase_id in verifiers:
        text = prompts[phase_id]
        assert _AGGREGATE_ONLY in text, f"{workflow}/{phase_id}: evidence-only pair"
        assert _AGGREGATE_MIXED in text, f"{workflow}/{phase_id}: mixed case"


@pytest.mark.parametrize("workflow", _PRECHECK_WORKFLOWS)
def test_precheck_classes_a_red_mutations_check_as_orchestrator_evidence(workflow: str) -> None:
    prompts = _prompts(workflow)
    verifiers = [pid for pid, text in prompts.items() if _RED_BLOCKS in text]
    assert verifiers, f"{workflow} has no verifier"
    for phase_id in verifiers:
        assert _ORCHESTRATOR_EVIDENCE in prompts[phase_id], f"{workflow}/{phase_id}"
        assert _AGGREGATE_PRECHECK in prompts[phase_id], f"{workflow}/{phase_id}"
