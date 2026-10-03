"""Why a registered child never started (#1398).

Mirrors the stable wire values the agentic-workspace child journal records on
``launch_failed`` intents. Harness adapters translate the wire string into this
vocabulary; the domain never matches on the raw string.
"""

from enum import StrEnum


class LaunchFailureReason(StrEnum):
    PROCESS_START_FAILED = "process_start_failed"
    CODEX_SANDBOX_UNAVAILABLE = "codex_sandbox_unavailable"
    # The native spawn tool reported failure without returning a child.
    NATIVE_TOOL_FAILED = "native_tool_failed"
    # The native spawn tool was interrupted before returning a child.
    NATIVE_TOOL_INTERRUPTED = "native_tool_interrupted"
    # The capture hook failed after committing the intent and denied the launch.
    CAPTURE_HOOK_FAILED = "capture_hook_failed"
    # The hook guard's watchdog stopped the capture hook after the intent committed.
    HOOK_WATCHDOG = "hook_watchdog"
    # The delegate probe could not reach the capture hook guard.
    CAPTURE_HOOK_UNREACHABLE = "capture_hook_unreachable"
    # A delegated Claude would start without credentials: Claude Code removes
    # its OAuth token from Bash subprocesses, so a Claude below a Claude Bash
    # call has none unless the workspace supplies one Claude reads itself.
    CLAUDE_NESTED_AUTH_UNAVAILABLE = "claude_nested_auth_unavailable"
    # A Claude parent's permission grant could not be read exactly, so the
    # delegated Claude could not be bounded by it.
    PARENT_PERMISSIONS_UNAVAILABLE = "parent_permissions_unavailable"
    # A nested delegate could not write the child journal (for example inside
    # a read-only Codex sandbox); recorded by the enclosing delegate.
    NESTED_JOURNAL_UNAVAILABLE = "nested_journal_unavailable"
