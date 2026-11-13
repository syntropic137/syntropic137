"""A validation phase that reports a capability FAILED must fail the run (#1085).

exec-eca6f017c58f reported `COMMENT: FAILED` and `CLOSE: FAILED` and completed
green: the prompt asked for the report lines and never said what a FAILED line
means for the phase's outcome, while the TASK_RESULT instruction appended to
every phase says a refused write is `success: true` with `side_effects: denied`.
For these workflows the capability IS the deliverable, so each prompt has to
say so itself.

Checked on the prompt each workflow.yaml's phase points at, so a phase whose
YAML stopped pointing at its prompt file is caught too. (Not through
`WorkflowDefinition.from_file`: it cannot resolve skills-injection's
package-relative skill ref, see `UNRESOLVABLE_ALONE` in
test_check_workflow_definitions.py.) Every report line that
can say FAILED, MISSING or an error must be named in a paragraph that also says
`success: false`: a line added later without that rule fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_VALIDATION = Path(__file__).resolve().parents[2] / "workflows" / "validation" / "workflows"

#: `KEY: <ok or FAILED>`, `KEY: <present|MISSING>`, `KEY: <ok or the error text>`
_FALLIBLE_PLACEHOLDER = re.compile(r"\b([A-Z][A-Z_]+): <[^>]*\b(?:FAILED|MISSING|error)\b")
#: `KEY: MISSING` written out in prose, as the sentinel lines are.
_FALLIBLE_LITERAL = re.compile(r"\b([A-Z][A-Z_]+): (?:FAILED|MISSING)\b")

#: A missing permission, token scope or injected skill is the deployment's
#: machinery, never the brief (phase-outcomes.mdx, `failure_reason`).
_OUTCOME_RULE = ("success: false", 'failure_reason: "platform"')


def _installed_prompts() -> dict[str, str]:
    """Every validation phase's prompt file, keyed `workflow-id/phase-id`."""
    prompts: dict[str, str] = {}
    for path in sorted(_VALIDATION.glob("*/workflow.yaml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for phase in workflow["phases"]:
            prompt = (path.parent / phase["prompt_file"]).read_text(encoding="utf-8")
            prompts[f"{workflow['id']}/{phase['id']}"] = prompt
    return prompts


_PROMPTS = _installed_prompts()


def _fallible_lines(prompt: str) -> set[str]:
    return {m.group(1) for m in _FALLIBLE_PLACEHOLDER.finditer(prompt)} | {
        m.group(1) for m in _FALLIBLE_LITERAL.finditer(prompt)
    }


def _outcome_paragraphs(prompt: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", prompt) if all(rule in p for rule in _OUTCOME_RULE)]


def test_every_validation_phase_is_collected() -> None:
    # A glob that silently matched nothing would make every test below vacuous.
    assert set(_PROMPTS) == {
        "selfhost-delegation-v1/build-and-delegate",
        "selfhost-github-ops-v1/exercise",
        "selfhost-long-push-v1/long_push",
        "selfhost-skills-injection-v1/report",
        "selfhost-skills-injection-v1/confirm",
    }


@pytest.mark.parametrize("phase", sorted(_PROMPTS))
def test_a_failed_capability_is_reported_as_success_false(phase: str) -> None:
    prompt = _PROMPTS[phase]
    fallible = _fallible_lines(prompt)
    assert fallible, f"{phase} reports no line that can fail; the parser no longer fits it"

    rules = _outcome_paragraphs(prompt)
    assert rules, (
        f"{phase} never says that a failed capability ends with TASK_RESULT "
        f"{' and '.join(_OUTCOME_RULE)}"
    )
    unbound = {line for line in fallible if not any(f"`{line}`" in p for p in rules)}
    assert not unbound, f"{phase}: {sorted(unbound)} can fail without failing the phase"
