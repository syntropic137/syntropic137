"""Which declared skills a phase actually used (#1269).

Declaring a skill installs it in the workspace; nothing about that says the
agent ever reached for it, and 1,911 recorded operations across 25 sessions
held no `Skill` call at all. This is the one place that turns a phase's start
pins and its Lane 2 timeline into that fact, so no caller has to know which
harness can be observed or which rows are a skill call.

The asymmetry is the harness's, not ours. Claude invokes a skill through its
`Skill` tool, so the call is on the timeline like any other. Codex has no such
tool: its skills arrive as context and their use leaves no signal, so a codex
phase is reported ``not_observable`` - never as zero invocations, which would
read as a measurement that the skills were ignored.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from syn_adapters.projections.session_tools import call_identity
from syn_api.types import InvokedSkillInfo, PhaseSkillUseInfo
from syn_domain.contexts.orchestration import SKILL_TOOL_NAME
from syn_shared.agents import AgentProvider
from syn_shared.events import TOOL_EXECUTION_STARTED

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_api.types import PhaseStartConfig, ToolOperation

#: Harnesses whose skill use reaches the timeline. Anything else is
#: ``not_observable``, so a new harness is not silently reported as unused.
_OBSERVABLE_PROVIDERS = frozenset({AgentProvider.CLAUDE.value})

#: Named when a call was observed but its start carried no skill name (a
#: completion with no start, or a row recorded before #1269) - counted, so a
#: call is never dropped for lacking one.
UNIDENTIFIED_SKILL = "(unidentified)"


def summarize_skill_use(
    pinned: PhaseStartConfig | None, ops: Sequence[ToolOperation] | None
) -> PhaseSkillUseInfo:
    """Skills this phase declared, and which of them its agent invoked.

    ``pinned`` is None when the start pins were not recorded or not readable,
    and ``ops`` is None when the timeline could not be read: either leaves the
    answer ``unavailable``, because the alternative is reporting a non-use
    nobody measured.
    """
    if pinned is None:
        return PhaseSkillUseInfo(status="unavailable")
    declared = [s.name for s in pinned.skills]
    if pinned.provider not in _OBSERVABLE_PROVIDERS:
        return PhaseSkillUseInfo(
            status="not_observable", declared=declared, provider=pinned.provider
        )
    if ops is None:
        return PhaseSkillUseInfo(status="unavailable", declared=declared, provider=pinned.provider)

    return PhaseSkillUseInfo(
        status="observed",
        declared=declared,
        provider=pinned.provider,
        invoked=[InvokedSkillInfo(name=n, count=c) for n, c in sorted(_invoked(ops).items())],
    )


def _invoked(ops: Sequence[ToolOperation]) -> Counter[str]:
    """How many distinct ``Skill`` calls named each skill."""
    # One count per CALL: a call's start and completion fold onto one identity,
    # and only the start carries the input that names the skill.
    names: dict[str, str] = {}
    for op in ops:
        if op.tool_name != SKILL_TOOL_NAME:
            continue
        identity = call_identity(op)
        if op.operation_type == TOOL_EXECUTION_STARTED or identity not in names:
            names[identity] = op.skill_name or UNIDENTIFIED_SKILL
    return Counter(names.values())
