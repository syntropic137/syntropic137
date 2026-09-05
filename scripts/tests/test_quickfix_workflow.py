"""`sdlc-quickfix-v1` must install as the thing its documentation promises.

This workflow has no verify phase. Its ONLY safeguards are prose in a prompt
file and two numbers in a YAML block, so the failure that matters is not "the
definition is invalid" - `check_workflow_definitions` already covers that for
every workflow in the tree - it is "the definition is still valid and the
safeguard is gone".

That failure is silent by construction. Emptying the bail-out section, or
deleting the paragraph that makes a PR declare it was never independently
verified, leaves a workflow that loads, converts, installs and runs. What
comes out the far end is an unreviewed behaviour change wearing a
trivial-change label, which is the one outcome this workflow exists to
prevent.

So these assertions run against the COMMAND the create endpoint builds, not
against the files on disk. `prompt_file` is resolved during load and the text
becomes `prompt_template`; `agent.model` is resolved through a fallback and
becomes `PhaseDefinition.model`. Reading the YAML back would confirm what was
typed while telling us nothing about what the platform installs.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseDefinition,
    )

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / "workflows" / "sdlc" / "quickfix" / "workflow.yaml"


@pytest.fixture(scope="module")
def installed_phase() -> PhaseDefinition:
    """The single phase exactly as `POST /workflows` would create it."""
    command = build_command_from_definition(WorkflowDefinition.from_file(_WORKFLOW))
    assert command.aggregate_id == "sdlc-quickfix-v1"
    assert len(command.phases) == 1, (
        "sdlc-quickfix-v1 is a SINGLE-phase workflow. A second phase means it is "
        "no longer the tool its prompt and the sdlc README describe, and the "
        "'no independent verification' notice its PRs carry may now be a lie."
    )
    return command.phases[0]


class TestTheGuardrailsSurviveIntoTheInstalledPrompt:
    """Each of these is a distinct way the fast path stops being safe.

    Substring assertions on prose are usually a poor test. Here the prose IS
    the mechanism: there is no code path to assert against, because the whole
    safeguard is an instruction the agent reads. A prompt tidy-up that drops
    one of these sections is the realistic regression, and it is invisible to
    every other check in the repository.
    """

    def test_it_names_the_workflow_to_fall_back_to(self, installed_phase: PhaseDefinition) -> None:
        """Bailing out is only actionable if the agent is told where to go.

        "This is out of scope, stopping" strands the task. The redirect is what
        turns a refusal into routing.
        """
        assert "sdlc-implement-v1" in (installed_phase.prompt_template or "")

    def test_it_forbids_attempting_an_out_of_scope_task(
        self, installed_phase: PhaseDefinition
    ) -> None:
        """The bail-out must be an instruction to STOP, not advice to be careful.

        Checked through the concrete out-of-scope categories rather than the
        word "scope", so deleting the list fails even if the heading survives.
        """
        prompt = (installed_phase.prompt_template or "").lower()
        for category in ("control flow", "error handling", "event schema", "projections"):
            assert category in prompt, f"out-of-scope list no longer names {category!r}"
        assert "bail out" in prompt

    def test_it_requires_the_pr_to_disclose_that_nothing_verified_it(
        self, installed_phase: PhaseDefinition
    ) -> None:
        """Without this, a quickfix PR is indistinguishable from a gated one.

        Reviewers here calibrate on cross-model review having happened. A PR
        that skipped it and does not say so borrows trust it did not earn, and
        the diff gives the reviewer no way to notice.
        """
        prompt = (installed_phase.prompt_template or "").lower()
        assert "no independent verification" in prompt
        assert "non-negotiable" in prompt

    def test_it_refuses_to_open_a_pr_on_a_failed_gate(
        self, installed_phase: PhaseDefinition
    ) -> None:
        prompt = (installed_phase.prompt_template or "").lower()
        assert "if a gate fails, do not open a pr" in prompt


class TestTheCostSettingsReachTheInstalledPhase:
    """`agent.model` and `timeout_seconds` are the drop-one-hop-later kind.

    Both are `None` by default on `PhaseYamlDefinition`, and `agent.model`
    reaches the domain only through the `self.model or agent_model` fallback in
    `to_domain`. If that hop broke, the phase would run on the platform default
    at the platform's default budget and nothing would report an error - the
    YAML would still say what we meant.
    """

    def test_it_runs_on_sonnet(self, installed_phase: PhaseDefinition) -> None:
        assert installed_phase.model == "sonnet", (
            "declared under `agent:`; if this is None the fallback in "
            "PhaseYamlDefinition.to_domain stopped carrying agent.model"
        )

    def test_its_budget_is_the_derived_one(self, installed_phase: PhaseDefinition) -> None:
        """1500s is derived in the workflow's own comment from measured costs.

        Asserted as an exact value, not `is not None`: the number IS the scope
        guardrail. Raising it is how a task too big for this workflow gets
        squeezed through it instead of being sent to `sdlc-implement-v1`, so a
        change to it should have to be argued for in a diff.
        """
        assert installed_phase.timeout_seconds == 1500
