"""Which declared skills a phase actually used (#1269).

Declaring a skill installs it in the workspace; nothing about that says the
agent ever reached for it, and 1,911 recorded operations across 25 sessions
held no `Skill` call at all. This is the one place that turns a phase's start
pins and its Lane 2 timeline into that fact, so no caller has to know which
harness can be observed, which rows are a skill call, or where the skill's
name sits in the call's input.

The asymmetry is the harness's, not ours. Claude invokes a skill through its
`Skill` tool, so the call is on the timeline like any other. Codex has no such
tool: its skills arrive as context and their use leaves no signal, so a codex
phase is reported ``not_observable`` - never as zero invocations, which would
read as a measurement that the skills were ignored.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import TYPE_CHECKING

from syn_adapters.projections.session_tools import call_identity
from syn_api.types import InvokedSkillInfo, PhaseSkillUseInfo
from syn_shared.agents import AgentProvider
from syn_shared.events import TOOL_EXECUTION_STARTED

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_adapters.projections.session_tools import ToolOperation
    from syn_api.types import PhaseStartConfig

#: The claude tool that invokes a skill, as the stream names it.
SKILL_TOOL_NAME = "Skill"

#: Harnesses whose skill use reaches the timeline. Anything else is
#: ``not_observable``, so a new harness is not silently reported as unused.
_OBSERVABLE_PROVIDERS = frozenset({AgentProvider.CLAUDE.value})

#: The preview is ``json.dumps(input)[:500]``, so a long ``args`` can cut the
#: JSON short. The name comes first in the observed shape and survives that.
_SKILL_FIELD = re.compile(r'"skill"\s*:\s*"([^"]+)"')

#: Named when a call was observed but its skill could not be read - counted,
#: so a call is never dropped for having an unreadable input.
UNIDENTIFIED_SKILL = "(unidentified)"


def _skill_name(input_preview: str | None) -> str:
    """The skill a `Skill` call invoked, read from its recorded input."""
    if not input_preview:
        return UNIDENTIFIED_SKILL
    try:
        parsed: object = json.loads(input_preview)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        name = parsed.get("skill")  # pyright: ignore[reportUnknownMemberType]
        if isinstance(name, str) and name:
            return name
    match = _SKILL_FIELD.search(input_preview)
    return match.group(1) if match else UNIDENTIFIED_SKILL


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
        return PhaseSkillUseInfo(status="not_observable", declared=declared)
    if ops is None:
        return PhaseSkillUseInfo(status="unavailable", declared=declared)

    # One count per CALL: a call's start and completion fold onto one identity,
    # and only the start carries the input that names the skill.
    names: dict[str, str] = {}
    for op in ops:
        if op.tool_name != SKILL_TOOL_NAME:
            continue
        identity = call_identity(op)
        if op.operation_type == TOOL_EXECUTION_STARTED or identity not in names:
            names[identity] = _skill_name(op.input_preview)
    counts = Counter(names.values())
    return PhaseSkillUseInfo(
        status="observed",
        declared=declared,
        invoked=[InvokedSkillInfo(name=n, count=c) for n, c in sorted(counts.items())],
    )
