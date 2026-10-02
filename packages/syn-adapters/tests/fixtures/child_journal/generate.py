"""Regenerate the child journal export fixtures from the real AW producer (#1398).

The fixtures are the exact stdout of ``agentic_session_store.child_export``
(the command ``WorkspaceChildJournalReader`` runs inside a workspace), written
by the pinned agentic-workspace session store. Regenerate after an AW bump:

    uv run --no-project --with lib/agentic-workspace/lib/python/agentic_session_store \\
        python packages/syn-adapters/tests/fixtures/child_journal/generate.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

from agentic_session_store.child_journal import (
    ChildBindingConflict,
    ChildCall,
    ChildJournal,
    LaunchFailureReason,
)

HERE = Path(__file__).parent


def call(tool_call_id: str, harness: str = "claude", target: str | None = None) -> ChildCall:
    return ChildCall("root-invocation", "attempt-1", harness, "parent-native", tool_call_id, target)


def export(path: Path) -> str:
    return subprocess.run(
        [sys.executable, "-m", "agentic_session_store.child_export", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def v3(path: Path) -> None:
    journal = ChildJournal(path)
    # Native child: intent pending, launch acknowledged and bound, then stopped.
    finished = call("native-finished")
    journal.register(finished, pending=True)
    journal.observe_launch(finished, "native-child-finished")
    journal.observe_stop("root-invocation", "attempt-1", "claude", "native-child-finished")
    # Native intent whose launch was never acknowledged (hook SIGKILLed).
    journal.register(call("native-pending", "codex"), pending=True)
    # Native launch failures with each hook-reported cause.
    for tool_call_id, reason in (
        ("native-tool-failed", LaunchFailureReason.NATIVE_TOOL_FAILED),
        ("native-tool-interrupted", LaunchFailureReason.NATIVE_TOOL_INTERRUPTED),
        ("native-hook-watchdog", LaunchFailureReason.HOOK_WATCHDOG),
    ):
        failed = call(tool_call_id)
        journal.register(failed, pending=True)
        journal.observe_launch_failure(failed, reason)
    # Delegates that never started, with their runner-reported cause.
    for tool_call_id, reason in (
        ("delegate-sandbox", LaunchFailureReason.CODEX_SANDBOX_UNAVAILABLE),
        ("delegate-unreachable", LaunchFailureReason.CAPTURE_HOOK_UNREACHABLE),
    ):
        delegate = call(tool_call_id, "claude", "codex")
        journal.register(delegate)
        journal.launch_failed(delegate, reason)
    # A second, different identity observed for an already-bound native child.
    conflicted = call("native-conflict")
    journal.register(conflicted, pending=True)
    journal.observe_launch(conflicted, "native-child-bound")
    with suppress(ChildBindingConflict):
        journal.observe_launch(conflicted, "native-child-rejected")


def v2(path: Path) -> None:
    journal = ChildJournal(path)
    delegate = call("delegate-ok", "claude", "codex")
    journal.register(delegate)
    journal.bind(delegate, "delegate-native")
    journal.launched(delegate)
    journal.finished(delegate, 0)


def main() -> None:
    for name, build in (("v3_native_lifecycle", v3), ("v2_delegate", v2)):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "children.sqlite"
            build(path)
            (HERE / f"{name}.json").write_text(export(path))


if __name__ == "__main__":
    main()
