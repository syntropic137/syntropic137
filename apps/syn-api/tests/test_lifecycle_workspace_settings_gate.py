"""Invalid workspace settings must abort startup, not degrade it (#954).

Codex pass 2 found that raising in the settings validator was not enough.
`WorkspaceSettings()` is first constructed inside a degradable service init,
whose exception is caught and appended to `degraded_reasons`. Startup then
returns Ok, `/health` answers 200 "healthy", and the npx setup flow prints
"Services healthy" -- while the workflow dispatcher never started.

That is the same false pass #954 is about, one layer further out: the operator
gets a confident green signal for a stack that cannot run workflows.
"""

from __future__ import annotations

import pytest

from syn_api.services.lifecycle import _validate_workspace_settings
from syn_api.types import Err, LifecycleError, Ok

pytestmark = pytest.mark.unit

_VAR = "SYN_WORKSPACE_DOCKER_IMAGE"


def test_valid_settings_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_VAR, raising=False)
    assert isinstance(_validate_workspace_settings(), Ok)


def test_explicit_override_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_VAR, "ghcr.io/example/other@sha256:deadbeef")
    assert isinstance(_validate_workspace_settings(), Ok)


def test_blank_aborts_startup_rather_than_degrading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The load-bearing assertion: Err, so the caller stops instead of continuing."""
    monkeypatch.setenv(_VAR, "")
    result = _validate_workspace_settings()
    assert isinstance(result, Err)
    assert result.error is LifecycleError.VALIDATION_FAILED


def test_the_failure_message_survives_to_the_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An abort with no explanation would trade one silent failure for another."""
    monkeypatch.setenv(_VAR, "   ")
    result = _validate_workspace_settings()
    assert isinstance(result, Err)
    assert "set but empty" in result.message
    assert "Unset it" in result.message


def test_the_gate_runs_before_degradable_services() -> None:
    """Ordering is the whole point: after them, the failure is already swallowed."""
    import inspect

    from syn_api.services import lifecycle

    source = inspect.getsource(lifecycle)
    gate = source.index("await _init_critical_path()")
    degradable = source.index("await _init_degradable_services(")
    assert gate < degradable, (
        "workspace validation must run on the critical path, before degradable "
        "service init catches and downgrades the exception"
    )
