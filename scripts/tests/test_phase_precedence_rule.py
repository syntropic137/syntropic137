"""A map or plan phase says which wins when the task text disagrees with it (#1267).

``sdlc-pr-review-v1``'s first phase put the caller's task text directly before
"produce a map, not a verdict". A task asking for a verdict left every run to
adjudicate the contradiction, and nothing guaranteed the map won. The rule now
sits immediately after ``$ARGUMENTS`` in each first phase of that shape.

Asserted on the upload bodies, not the ``.md`` files: they are what
``syn workflow install`` POSTs after inlining the prompt files, and
``workflow-yaml-reference.test.ts`` pins them to the CLI loader's output.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, RootModel

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_UPLOAD_BODIES = _REPO_ROOT / "apps/syn-cli-node/tests/fixtures/workflow-upload-bodies.json"

_RULE_OPENING = "The task above says WHAT to"
_RULE_RESOLUTION = "where the two disagree, these instructions win"


class _Phase(BaseModel):
    # The fixture carries every upload field; only these two are read here.
    model_config = ConfigDict(frozen=True, extra="ignore")
    id: str
    prompt_template: str


class _Body(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    phases: list[_Phase]


_BODIES = (
    RootModel[dict[str, _Body]].model_validate_json(_UPLOAD_BODIES.read_text(encoding="utf-8")).root
)

# (workflow file, first phase, a sentence of that phase's own job the rule must precede or follow)
_MAP_AND_PLAN_PHASES = [
    ("workflows/sdlc/pr-review/workflow.yaml", "investigate", "produce a map, not a verdict"),
    (
        "workflows/sdlc/pr-review-slp/workflow.yaml",
        "investigate",
        "Dispatch one subagent per leverage point",
    ),
    ("workflows/sdlc/research-plan/workflow.yaml", "research", "You are not proposing a solution"),
    (
        "workflows/sdlc/research-experiment-plan/workflow.yaml",
        "research",
        "You are not proposing a solution",
    ),
    ("workflows/sdlc/decision-record/workflow.yaml", "options", "A later phase chooses"),
    (
        "workflows/examples/implementation.yaml",
        "research",
        "Output a codebase analysis with dependency map",
    ),
]


def _prompt(workflow: str, phase_id: str) -> str:
    phases = _BODIES[workflow].phases
    assert phases[0].id == phase_id, f"{workflow}: first phase is {phases[0].id}, not {phase_id}"
    return phases[0].prompt_template


@pytest.mark.parametrize(("workflow", "phase_id", "own_job"), _MAP_AND_PLAN_PHASES)
def test_rule_is_the_paragraph_right_after_the_task_text(
    workflow: str, phase_id: str, own_job: str
) -> None:
    prompt = _prompt(workflow, phase_id)
    after_task = prompt.split("\n$ARGUMENTS\n\n", 1)[1]
    first_paragraph = after_task.split("\n\n", 1)[0]
    assert first_paragraph.startswith(_RULE_OPENING)
    assert _RULE_RESOLUTION in " ".join(first_paragraph.split())
    # It is the same prompt, not the rule landing in some other phase's text.
    assert own_job in " ".join(prompt.split())


def test_pr_review_rule_precedes_the_map_instruction_and_routes_verdicts_to_the_final_phase() -> (
    None
):
    prompt = _prompt("workflows/sdlc/pr-review/workflow.yaml", "investigate")
    rule_at = prompt.index(_RULE_OPENING)
    assert prompt.index("$ARGUMENTS") < rule_at < prompt.index("produce a map, not a verdict")
    rule = " ".join(prompt[rule_at:].split("\n\n", 1)[0].split())
    assert "A verdict, a sign-off or an output format" in rule
    assert "final phase" in rule
    assert "do not act on it here" in rule


def test_rule_is_stated_once_per_prompt() -> None:
    for workflow, phase_id, _ in _MAP_AND_PLAN_PHASES:
        assert _prompt(workflow, phase_id).count(_RULE_OPENING) == 1, workflow
