"""A phase that declares skills must be able to invoke them (#1269).

`--tools` restricts what the agent can use (#964). A phase that declared
skills and scoped its tools without naming `Skill` got its skills installed and
the one tool that invokes them withheld. `sdlc-implement-v3` declares skills on
every phase and lists `Skill` on none, and its executions recorded zero `Skill`
calls in every phase: the expected result of a tool that was never offered, not
a capture gap.

These tests start from the real shipped workflow and check the command the
agent is launched with, because that is where the grant was lost. A test that
inspected the `AgentConfiguration` alone would have passed just as well against
a grant that was then dropped on the way to the CLI.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from syn_domain.contexts.orchestration._shared.resolved_skill import ResolvedSkill
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_shared.agents import AgentProvider

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
_IMPLEMENT_V3 = _REPO / "workflows" / "sdlc" / "implement-v3" / "workflow.yaml"


class _Template:
    """The attributes `_get_executable_phases` reads from a stored template."""

    def __init__(self, definition: WorkflowDefinition, *, with_skills: bool = True) -> None:
        domain = [p.to_domain() for p in definition.phases]
        if not with_skills:
            domain = [p.model_copy(update={"skills": ()}) for p in domain]
        self.phases = domain
        self.claude_plugins = ()
        self.skills = tuple(definition.skills) if with_skills else ()


async def _resolve(workflow_refs: object, phase_refs: object) -> tuple[ResolvedSkill, ...]:
    """Stands in for the lock lookup: one resolved skill per declared ref."""
    refs = [*cast("list[object]", workflow_refs), *cast("list[object]", phase_refs)]
    return tuple(
        ResolvedSkill(
            skill_name=getattr(ref, "skill_name"),  # noqa: B009 - SkillRef double-free
            source_url=getattr(ref, "source_url"),  # noqa: B009
            version=getattr(ref, "version"),  # noqa: B009
            resolved_sha="0" * 64,
            tree_storage_prefix="skills/test",
        )
        for ref in refs
    )


def _handler() -> ExecuteWorkflowHandler:
    handler = ExecuteWorkflowHandler.__new__(ExecuteWorkflowHandler)
    handler._phase_plugin_resolver = None
    handler._phase_skill_resolver = _resolve
    return handler


def _tools_flag(cmd: list[str]) -> list[str] | None:
    if "--tools" not in cmd:
        return None
    return cmd[cmd.index("--tools") + 1].split(",")


async def _claude_commands(template: _Template) -> dict[str, list[str]]:
    from syn_api._wiring import _build_claude_command

    phases = await _handler()._get_executable_phases(cast("object", template))  # type: ignore[arg-type]
    return {
        p.phase_id: _build_claude_command(p, "prompt")
        for p in phases
        if p.agent_config.provider == AgentProvider.CLAUDE
    }


async def test_every_scoped_claude_phase_of_implement_v3_is_offered_the_skill_tool() -> None:
    definition = WorkflowDefinition.from_file(_IMPLEMENT_V3)
    commands = await _claude_commands(_Template(definition))

    # The shipped YAML scopes tools on these phases and names `Skill` on none,
    # which is the shape #1269 measured. If it ever lists `Skill` itself, this
    # test stops proving anything, so fail loudly rather than pass vacuously.
    declared = {p.id: list(p.allowed_tools) for p in definition.phases}
    scoped = [pid for pid, cmd in commands.items() if _tools_flag(cmd) is not None]
    assert scoped, "implement-v3 no longer scopes any claude phase's tools"
    assert all("Skill" not in declared[pid] for pid in scoped)

    for pid in scoped:
        tools = _tools_flag(commands[pid])
        assert tools is not None
        assert "Skill" in tools, f"{pid} declares skills but cannot invoke them: {tools}"
        # The grant adds one tool and widens nothing else.
        assert sorted(t for t in tools if t != "Skill") == sorted(declared[pid])


async def test_a_phase_without_skills_is_not_granted_the_skill_tool() -> None:
    definition = WorkflowDefinition.from_file(_IMPLEMENT_V3)
    commands = await _claude_commands(_Template(definition, with_skills=False))

    for pid, cmd in commands.items():
        tools = _tools_flag(cmd)
        assert tools is None or "Skill" not in tools, pid
