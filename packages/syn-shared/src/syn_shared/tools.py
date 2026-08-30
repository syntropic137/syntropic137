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
