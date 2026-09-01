"""Type-safe Claude tool names for phase `allowed_tools` (issue #964).

WHY AN ENUM: the shipped workflows declared lowercase `bash` and `computer`.
Claude's built-ins are `Bash`, `Read`, `Edit`, `Write`. While the declaration
was inert nothing noticed; the moment it restricts anything, a case typo
becomes an agent that cannot run a command, discovered at runtime on an
unattended CI trigger. A closed vocabulary moves that to authoring time.

PROVENANCE: these names are the `defaults.allowed_tools` block of the
omni-agent workspace image manifest
(`providers/workspaces/omni-agent/manifest.yaml`), which is the image these
phases actually execute in - not a list assembled from memory.

BOUNDARY: by the AGENTS.md test ("if it changes when Anthropic ships a new
CLI version, it belongs in agentic-primitives") this vocabulary is harness
knowledge and belongs in the submodule beside the harness adapters. It is
here because syn137 needs to VALIDATE at authoring time and the submodule
exposes no such seam yet; #964 tracks moving it behind a harness port.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


class ToolName(StrEnum):
    """A Claude built-in tool that a phase may declare.

    Values are case-sensitive because the CLI's `--tools` flag is.
    """

    BASH = "Bash"
    EDIT = "Edit"
    GLOB = "Glob"
    GREP = "Grep"
    LS = "LS"
    MULTI_EDIT = "MultiEdit"
    READ = "Read"
    TASK = "Task"
    TODO_READ = "TodoRead"
    TODO_WRITE = "TodoWrite"
    WEB_FETCH = "WebFetch"
    WEB_SEARCH = "WebSearch"
    WRITE = "Write"


_BY_CASEFOLDED: dict[str, ToolName] = {member.value.casefold(): member for member in ToolName}


def canonical_tool_name(raw: str) -> ToolName | None:
    """Resolve an authored tool name, tolerating case only.

    Case is forgiven because every shipped workflow got it wrong and the
    intent is unambiguous. Nothing else is: an unknown name returns None so
    the caller can reject it rather than pass a string the CLI will silently
    treat as "no such tool".
    """
    return _BY_CASEFOLDED.get(raw.strip().casefold())


class UnsupportedToolNameError(ValueError):
    """A phase declared a tool name outside the closed vocabulary."""

    def __init__(self, unknown: Sequence[str], *, phase_id: str | None = None) -> None:
        where = f"Phase '{phase_id}': " if phase_id else ""
        known = ", ".join(sorted(t.value for t in ToolName))
        super().__init__(
            f"{where}unknown tool name(s): {', '.join(unknown)}. Valid tools "
            f"are: {known}. A phase cannot be restricted to a tool that does "
            "not exist - the agent would silently lose every tool it needs."
        )


def require_supported_tools(
    declared: Sequence[str],
    *,
    phase_id: str | None = None,
) -> tuple[ToolName, ...]:
    """Canonicalise a stored tool declaration, or raise.

    WHY THIS EXISTS AT THE EXECUTION BOUNDARY and not only in the YAML
    validator: a template stored before #964 is rehydrated straight from its
    historical ``WorkflowTemplateCreated`` event and never sees that
    validator, exactly as ``require_executable_provider`` documents for
    providers.

    Measured against the deployment before this was written: 11 phases across
    4 installed workflows declare ``git``, which is not a tool on any harness.
    While the declaration was inert that cost nothing. The moment it restricts
    availability, silently dropping the unknown name would hand those phases
    ``--tools Bash`` and take away every other tool they actually use, which
    is a worse failure than refusing: it looks like the agent got dumber.

    So: unknown names are refused, loudly, naming the phase. Case is still
    forgiven, because that is unambiguous and every shipped workflow got it
    wrong.
    """
    resolved: list[ToolName] = []
    unknown: list[str] = []
    for index, raw in enumerate(declared):
        # A blank or non-string entry is REFUSED, not skipped. Skipping it
        # would contradict the rule this function exists to enforce:
        # `allowed_tools: [""]` would normalise to an empty tuple, and an empty
        # tuple means "declared nothing", so the phase would run completely
        # unrestricted while its author believed it was scoped.
        if not isinstance(raw, str) or not raw.strip():
            unknown.append(f"<empty at index {index}>" if isinstance(raw, str) else repr(raw))
            continue
        match = canonical_tool_name(raw)
        if match is None:
            unknown.append(raw.strip())
        else:
            resolved.append(match)
    if unknown:
        raise UnsupportedToolNameError(unknown, phase_id=phase_id)
    return tuple(resolved)
