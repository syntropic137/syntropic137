"""What counts as WORK for the fallback rule: both sides of the line (#1825)."""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.side_effect_free import (
    command_changes_nothing,
    tool_call_changes_nothing,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "command",
    [
        "/bin/zsh -lc 'cat one.txt'",
        "/bin/bash -lc 'sed -n 1,200p a.py'",
        "/bin/zsh -lc 'rg --no-config -n fallback packages | head -20'",
        "/bin/zsh -lc 'git -C repo --no-pager diff --no-ext-diff --no-textconv origin/main...HEAD'",
        "/bin/zsh -lc 'git -P log --no-ext-diff --no-textconv --no-show-signature -p -5'",
        "/bin/zsh -lc 'git --no-pager show --no-ext-diff --no-textconv --no-show-signature HEAD'",
        "/bin/zsh -lc 'git --no-pager blame --no-textconv a.py && git -P rev-parse HEAD'",
        "/bin/zsh -lc 'gh pr diff 1819'",
        "/bin/zsh -lc 'ls -1 2>/dev/null; find . -name \"*.py\"'",
        "grep -rn x .",
        "/bin/zsh -lc 'git --no-pager diff --no-ext-diff --no-textconv 2>&1 | head; ls >/dev/null'",
    ],
)
def test_a_command_that_only_reads_changes_nothing(command: str) -> None:
    assert command_changes_nothing(command)


@pytest.mark.parametrize(
    "command",
    [
        "/bin/zsh -lc 'git push origin HEAD'",
        "/bin/zsh -lc 'git commit -am x'",
        "/bin/zsh -lc 'git checkout -b x'",
        "/bin/zsh -lc 'cat a > b'",
        "/bin/zsh -lc 'cat a >> b'",
        "/bin/zsh -lc 'echo x | tee b'",
        "/bin/zsh -lc 'sed -i s/a/b/ f.py'",
        "/bin/zsh -lc 'sed -n 1,5w out f.py'",
        "/bin/zsh -lc 'find . -delete'",
        "/bin/zsh -lc 'find . -exec rm {} +'",
        "/bin/zsh -lc 'find . -fls out'",
        "/bin/zsh -lc 'git diff --output=patch'",
        "/bin/zsh -lc 'rg --pre ./script x'",
        "/bin/zsh -lc 'cat a && rm b'",
        "/bin/zsh -lc 'ls $(rm -rf x)'",
        "/bin/zsh -lc 'python -c \"open(1)\"'",
        "/bin/zsh -lc 'gh pr comment 1 -b x'",
        "/bin/zsh -lc 'sort -o out in'",
        "/bin/zsh -lc 'just test'",
        "/bin/zsh -lc 'cat \"unterminated'",
        "",
        # Review round 1 of #1825: each of these ran, or could run, a write.
        "echo reviewed & touch review-output",
        "echo reviewed & git commit -am reviewed",
        "echo reviewed & git push origin HEAD",
        "ls > /dev/null-review-output",
        "git diff --ext-diff",
        "git diff --textconv",
        "git cat-file --filters HEAD:a.py",
        "git grep --open-files-in-pager=touch pattern",
        "git grep -Otouch pattern",
        # Installing a driver that a later plain `git diff` runs is itself work.
        "git config diff.external ./driver",
        "export GIT_EXTERNAL_DIFF=./driver",
        "GIT_EXTERNAL_DIFF=./driver git diff",
        "git -c diff.external=./driver diff",
        # Review round 2 of #1825: git and rg run what their CONFIGURATION names,
        # wherever it was installed, unless the invocation switches it off.
        "git diff",
        "git --no-pager diff",
        "git --no-pager diff --no-ext-diff",
        "git --no-pager diff --no-textconv",
        "git diff --no-ext-diff --no-textconv",
        "git --no-pager log --no-ext-diff --no-textconv -p",
        "git --no-pager show --no-ext-diff --no-textconv",
        "git --no-pager blame a.py",
        "git --no-pager status",
        "git rev-parse HEAD",
        "rg -n x .",
    ],
)
def test_a_command_that_may_write_is_work(command: str) -> None:
    assert not command_changes_nothing(command)


@pytest.mark.parametrize(("tool", "command"), [("Read", None), ("Grep", None), ("Bash", "ls")])
def test_read_only_tool_calls_change_nothing(tool: str, command: object) -> None:
    assert tool_call_changes_nothing(tool, command)


@pytest.mark.parametrize(
    ("tool", "command"),
    [("Edit", None), ("Write", None), ("Bash", None), ("Bash", "rm x"), ("SomeNewTool", None)],
)
def test_every_other_tool_call_is_work(tool: str, command: object) -> None:
    assert not tool_call_changes_nothing(tool, command)


def _collector() -> ObservabilityCollector:
    return ObservabilityCollector(
        writer=None,
        session_id="s",
        execution_id="e",
        phase_id="verify",
        workspace_id=None,
        requested_model=None,
    )


class TestTheCollectorWitness:
    async def test_reading_is_activity_but_not_a_write(self) -> None:
        collector = _collector()
        await collector.record_tool_started("Read", "t-1", "{}", changes_nothing=True)
        await collector.record_tool_completed("Read", "t-1", True, None, changes_nothing=True)
        collector.note_agent_activity(changed_nothing=True)

        assert collector.saw_agent_activity
        assert not collector.may_have_written

    async def test_unqualified_activity_is_a_possible_write(self) -> None:
        collector = _collector()
        await collector.record_hook_event({"event_type": "x"})

        assert collector.may_have_written

    async def test_a_write_is_not_undone_by_later_reads(self) -> None:
        collector = _collector()
        await collector.record_tool_started("Edit", "t-1", "{}")
        await collector.record_tool_started("Read", "t-2", "{}", changes_nothing=True)

        assert collector.may_have_written
