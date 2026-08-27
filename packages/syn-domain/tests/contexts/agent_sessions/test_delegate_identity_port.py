"""The port syn137 depends on for harness-native delegate identity (#895).

WHY a port rather than an implementation: knowing that codex emits
``thread.started.thread_id`` is knowledge about a CLI, not about our domain. It
changes when OpenAI ships a new codex version, so per the boundary rule in
AGENTS.md it belongs in agentic-primitives beside the existing
``harnesses/{claude,codex}`` adapters.

These tests use a double deliberately. The point of the port is that the domain
is testable without the submodule, so this work does not serialise behind the
image build -> release channel -> pin bump chain.
"""

from __future__ import annotations

import json

import pytest

from syn_domain.contexts.agent_sessions.ports.DelegateIdentityPort import (
    DelegateIdentityPort,
)

_CODEX_THREAD_ID = "01a04470-3a1c-7883-9229-632918155605"


class _FakeCodexIdentity:
    """Stands in for the agentic-primitives codex harness adapter."""

    def native_session_id_from_stream(self, line: str) -> str | None:
        payload = json.loads(line)
        if payload.get("type") != "thread.started":
            return None
        thread_id = payload.get("thread_id")
        return thread_id if isinstance(thread_id, str) and thread_id else None


@pytest.mark.unit
def test_a_double_satisfies_the_port() -> None:
    """Structural typing: no import from the submodule is required."""
    identity: DelegateIdentityPort = _FakeCodexIdentity()
    line = json.dumps({"type": "thread.started", "thread_id": _CODEX_THREAD_ID})

    assert identity.native_session_id_from_stream(line) == _CODEX_THREAD_ID


@pytest.mark.unit
def test_only_the_line_that_carries_identity_is_trusted() -> None:
    """Mirrors the lesson already learned in agentic-primitives (#792): reading
    an id off ANY line let an unrelated session's id through. A line of the
    wrong type yields nothing even when it carries an id-shaped field.
    """
    identity: DelegateIdentityPort = _FakeCodexIdentity()
    line = json.dumps({"type": "item.completed", "thread_id": "WRONG-SESSION"})

    assert identity.native_session_id_from_stream(line) is None


@pytest.mark.unit
def test_an_empty_id_is_not_an_id() -> None:
    """An empty string would bind a child to nothing while looking successful."""
    identity: DelegateIdentityPort = _FakeCodexIdentity()
    line = json.dumps({"type": "thread.started", "thread_id": ""})

    assert identity.native_session_id_from_stream(line) is None


@pytest.mark.unit
def test_port_is_runtime_checkable_so_wiring_can_be_asserted() -> None:
    """Production wiring must be able to prove it passed a real adapter."""
    assert isinstance(_FakeCodexIdentity(), DelegateIdentityPort)


@pytest.mark.unit
def test_an_object_without_the_method_does_not_satisfy_the_port() -> None:
    """Guards the guard: if this passed, the check above would prove nothing."""

    class _NotAnIdentity:
        pass

    assert not isinstance(_NotAnIdentity(), DelegateIdentityPort)
