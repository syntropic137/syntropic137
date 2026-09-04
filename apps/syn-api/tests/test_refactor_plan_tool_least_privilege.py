"""A planning phase must not be handed a shell it never uses (#1039).

``characterize`` and ``seams`` are read-and-write planning phases: they read
the target module and the previous phase's artifact, and they write a
markdown deliverable. Neither prompt asks the agent to run tests, call ``gh``,
push, or invoke a shell at all - both end with "Do not write code or tests".
They were nevertheless granted ``Bash``, which under
``--dangerously-skip-permissions`` is unreviewed authority to run anything in
the workspace.

``coverage-gate`` is the phase that legitimately needs it: its entire job is to
MEASURE coverage by invoking the tooling, and a gate that reports coverage it
did not run is the failure mode the whole workflow exists to prevent. So the
assertion here is not "no planning workflow gets Bash" - it is that each phase
gets a shell only where its prompt uses one, which is why the coverage-gate
expectation below is deliberately the opposite of the other two.

Scored at the CONSUMING hop. ``allowed_tools`` travels YAML -> frontmatter
merge -> ``AgentConfiguration`` -> the comma-joined ``--tools`` argument, and a
grant dropped or widened at any of those hops is invisible to a test that only
reads the YAML back.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from syn_api._wiring import _build_claude_command
from syn_domain.contexts.orchestration._shared.ExecutionValueObjects import ExecutablePhase
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    _build_agent_config_from_phase,
)

pytestmark = pytest.mark.unit

WORKFLOW = (
    Path(__file__).resolve().parents[3] / "workflows" / "sdlc" / "refactor-plan" / "workflow.yaml"
)


@dataclass(frozen=True)
class _StoredPhase:
    """The shape ``_build_agent_config_from_phase`` reads off a stored phase.

    It takes ``object`` and uses ``getattr``, because a rehydrated template is
    not a ``PhaseDefinition``. Spelling the fields out here keeps the test
    honest about which ones actually reach the command builder.
    """

    phase_id: str
    model: str | None
    provider: str | None
    allow_delegation: bool
    allowed_tools: tuple[str, ...]
    sandbox: str | None


def _tools_in_argv(phase_id: str) -> list[str]:
    """The tools the claude CLI is actually told this phase may use."""
    definition = WorkflowDefinition.from_file(WORKFLOW)
    phase = next(p for p in definition.phases if p.id == phase_id)
    agent = getattr(phase, "agent", None)
    stored = _StoredPhase(
        phase_id=phase.id,
        model=phase.model,
        provider=getattr(agent, "provider", None),
        allow_delegation=bool(getattr(agent, "allow_delegation", False)),
        allowed_tools=tuple(phase.allowed_tools),
        sandbox=getattr(phase, "sandbox", None),
    )

    argv = _build_claude_command(
        ExecutablePhase(
            phase_id=phase.id,
            name=phase.name,
            order=phase.order,
            agent_config=_build_agent_config_from_phase(stored),
        ),
        "PROMPT",
    )
    assert "--tools" in argv, f"phase '{phase_id}' reached the CLI with no tool restriction at all"
    return argv[argv.index("--tools") + 1].split(",")


class TestPlanningPhasesGetNoShell:
    @pytest.mark.parametrize("phase_id", ["characterize", "seams"])
    def test_no_bash_reaches_the_cli(self, phase_id: str) -> None:
        assert "Bash" not in _tools_in_argv(phase_id)

    @pytest.mark.parametrize("phase_id", ["characterize", "seams"])
    def test_the_tools_they_do_use_survive(self, phase_id: str) -> None:
        """Removing a grant must not have removed the rest of them.

        ``seams`` cites files and symbols and ``characterize`` reads the gate's
        artifact; both write a deliverable. A phase stripped to nothing would
        pass the assertion above and produce no plan.
        """
        assert _tools_in_argv(phase_id) == ["Read", "Grep", "Glob", "Write"]


class TestTheGateKeepsTheShellItNeeds:
    def test_coverage_gate_still_gets_bash(self) -> None:
        """Guards the blunt fix: deleting Bash everywhere would break the gate."""
        assert "Bash" in _tools_in_argv("coverage-gate")


class TestTheTwoDeclarationsAgree:
    """The prompt's own frontmatter also declares ``allowed-tools``.

    ``_resolve_phase_prompt_file`` merges frontmatter only into keys the YAML
    left unset, so the YAML wins and a stale frontmatter list changes nothing
    about what runs - it just tells the next reader something false about the
    authority this phase holds. That is the inert declaration ADR-069 D5
    forbids, so drift between the two is a failure rather than a cosmetic
    difference.
    """

    @pytest.mark.parametrize("phase_id", ["coverage-gate", "characterize", "seams", "revise"])
    def test_frontmatter_matches_the_yaml(self, phase_id: str) -> None:
        raw = yaml.safe_load(WORKFLOW.read_text())
        declared = next(p for p in raw["phases"] if p["id"] == phase_id)
        prompt = (WORKFLOW.parent / declared["prompt_file"]).read_text()
        frontmatter = yaml.safe_load(prompt.split("---")[1])
        assert [t.strip() for t in frontmatter["allowed-tools"].split(",")] == declared[
            "allowed_tools"
        ]
