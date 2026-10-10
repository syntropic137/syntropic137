"""What a phase shipped reaches the ledger from its own stream, both harnesses.

Driven through the real processors and collector, with the real hook emitter
for the commit line, so the test breaks if any hop stops passing it on.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from agentic_events import EventEmitter

from syn_domain.contexts.orchestration._shared.shipped_ledger import (
    CommitShipped,
    ExecutionAttribution,
    PullRequestMerged,
    PullRequestOpened,
)
from syn_domain.contexts.orchestration._shared.shipped_recorder import ShippedRecorder
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.unit

URL = "https://github.com/acme/api/pull/42"


class _Ledger:
    def __init__(self) -> None:
        self.commits: list[CommitShipped] = []
        self.prs: list[PullRequestOpened] = []

    async def record_commit(self, commit: CommitShipped) -> None:
        self.commits.append(commit)

    async def record_pull_request_opened(self, pr: PullRequestOpened) -> None:
        self.prs.append(pr)

    async def record_pull_request_merged(self, merge: PullRequestMerged) -> None: ...

    async def daily(self, *_: object) -> list[object]:
        return []


class _Workspace:
    async def interrupt(self) -> bool:
        return True


async def _lines(*lines: str) -> AsyncIterator[str]:
    for line in lines:
        yield line


def _collector(ledger: _Ledger) -> ObservabilityCollector:
    recorder = ShippedRecorder(
        ledger=ledger,
        attribution=ExecutionAttribution("exec-1", "wf-1", "Implement", ("acme/api",)),
        clock=lambda: datetime(2026, 10, 9, tzinfo=UTC),
    )
    return ObservabilityCollector(
        writer=None,
        session_id="s-1",
        execution_id="exec-1",
        phase_id="p-1",
        workspace_id=None,
        requested_model=None,
        shipped=recorder,
    )


def _claude_tool(tool_use_id: str, command: str, output: str, is_error: bool) -> tuple[str, str]:
    use = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": "Bash",
                    "input": {"command": command},
                }
            ]
        },
    }
    result = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": output,
                    "is_error": is_error,
                }
            ]
        },
    }
    return json.dumps(use), json.dumps(result)


def _commit_hook_line(sha: str) -> str:
    buffer = io.StringIO()
    EventEmitter(session_id="s-1", provider="claude", output=buffer).git_commit(
        message="feat: x", sha=sha, branch="feat", repo="api"
    )
    return buffer.getvalue().strip()


@pytest.mark.asyncio
async def test_claude_stream_records_commits_and_created_prs() -> None:
    ledger = _Ledger()
    processor = EventStreamProcessor(
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        observability=None,
        controller=None,
        execution_id="exec-1",
        phase_id="p-1",
        session_id="s-1",
        workspace_id=None,
        agent_model=None,
        collector=_collector(ledger),
    )
    created = _claude_tool("t1", "git push && gh pr create --fill", f"{URL}\n", False)
    failed = _claude_tool("t2", "gh pr create --fill", "https://github.com/acme/api/pull/7", True)
    quoted = _claude_tool("t3", "echo 'gh pr create'", "https://github.com/acme/api/pull/8", False)
    await processor.process_stream(
        _lines(_commit_hook_line("abc123"), *created, *failed, *quoted), _Workspace()
    )
    assert [(c.sha, c.repository) for c in ledger.commits] == [("abc123", "acme/api")]
    assert [(p.repository, p.number) for p in ledger.prs] == [("acme/api", 42)]


@pytest.mark.asyncio
async def test_codex_stream_records_created_prs_on_exit_code_zero_only() -> None:
    ledger = _Ledger()
    processor = CodexStreamProcessor(
        tokens=TokenAccumulator(),
        collector=_collector(ledger),
        controller=None,
        execution_id="exec-1",
        phase_id="p-1",
        session_id="s-1",
        agent_model=None,
        rollout=None,
    )

    def completed(item_id: str, exit_code: int, command: str, output: str) -> str:
        item = {
            "id": item_id,
            "type": "command_execution",
            "command": command,
            "aggregated_output": output,
            "exit_code": exit_code,
            "status": "completed",
        }
        return json.dumps({"type": "item.completed", "item": item})

    await processor.process_stream(
        _lines(
            completed("c1", 0, "/bin/bash -lc 'gh pr create --fill'", f"{URL}\n"),
            completed(
                "c2", 1, "/bin/bash -lc 'gh pr create --fill'", "https://github.com/acme/api/pull/9"
            ),
        ),
        _Workspace(),
    )
    assert [(p.repository, p.number) for p in ledger.prs] == [("acme/api", 42)]
