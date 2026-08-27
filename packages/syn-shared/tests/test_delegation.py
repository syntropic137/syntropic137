"""Tests for delegated-CLI invocation RECOGNITION (telemetry only, see #894)."""

from __future__ import annotations

import pytest

from syn_shared.agents import AgentProvider
from syn_shared.delegation import (
    DELEGATION_TARGET_BY_PRIMARY,
    DelegationTarget,
    looks_like_delegation_command,
)

pytestmark = pytest.mark.unit


def test_each_primary_provider_delegates_to_the_other_cli() -> None:
    assert DELEGATION_TARGET_BY_PRIMARY[AgentProvider.CLAUDE] is DelegationTarget.CODEX
    assert DELEGATION_TARGET_BY_PRIMARY[AgentProvider.CODEX] is DelegationTarget.CLAUDE
    # Every executable provider must have a delegate, or a delegating phase of
    # that provider could never be asserted on.
    assert set(DELEGATION_TARGET_BY_PRIMARY) == set(AgentProvider)


@pytest.mark.parametrize(
    "command",
    [
        "codex exec 'do the thing'",
        "codex exec --json --full-auto 'review'",
        "bash -lc 'codex exec --json \"review the diff\"'",
        "cd /workspace && codex exec 'go'",
        "/usr/local/bin/codex exec 'go'",
        "codex --cd /workspace exec 'go'",
    ],
)
def test_codex_exec_invocations_are_recognised(command: str) -> None:
    assert looks_like_delegation_command(command, DelegationTarget.CODEX) is True


@pytest.mark.parametrize(
    "command",
    [
        "",
        "grep -rn codex .",
        "echo 'ask codex about it'",
        "cat /opt/agentic/plugins/delegation/skills/delegating-to-codex/SKILL.md",
        "codex --version",
        "claude -p 'review'",
    ],
)
def test_non_codex_delegations_are_not_recognised(command: str) -> None:
    assert looks_like_delegation_command(command, DelegationTarget.CODEX) is False


@pytest.mark.parametrize(
    "command",
    [
        "claude -p 'review this diff'",
        "claude --print 'review this diff'",
        "bash -lc \"claude -p --model sonnet 'review'\"",
        "/usr/local/bin/claude -p 'go'",
    ],
)
def test_claude_print_invocations_are_recognised(command: str) -> None:
    assert looks_like_delegation_command(command, DelegationTarget.CLAUDE) is True


@pytest.mark.parametrize(
    "command",
    [
        "",
        "claude --version",
        "grep -rn claude .",
        "ls /home/claude-user",
        "codex exec 'go'",
    ],
)
def test_non_claude_delegations_are_not_recognised(command: str) -> None:
    assert looks_like_delegation_command(command, DelegationTarget.CLAUDE) is False
