"""``claude --model`` receives an explicit, allowed id, never an alias.

The argv is what the workspace runs, so these test the command builder, not
the map it reads: a resolution dropped one hop before the CLI would pass every
test of ``resolve_claude_model`` and still let the CLI pick.
"""

from __future__ import annotations

import pytest

from syn_shared.agents import AgentProvider, ModelId, RetiredModelError

pytestmark = pytest.mark.unit


def _phase(model: str):
    from syn_domain.contexts.orchestration._shared.ExecutionValueObjects import (
        AgentConfiguration,
        ExecutablePhase,
    )

    return ExecutablePhase(
        phase_id="p1",
        name="p1",
        order=0,
        prompt_template="do the thing",
        agent_config=AgentConfiguration(provider=AgentProvider.CLAUDE, model=model),
    )


def _model_flag(argv: list[str]) -> str:
    return argv[argv.index("--model") + 1]


@pytest.mark.parametrize(
    ("declared", "launched"),
    [("sonnet", "claude-sonnet-5-5"), ("opus", "claude-opus-5-5")],
)
def test_alias_is_launched_as_its_explicit_id(declared: str, launched: str) -> None:
    from syn_api._wiring_agent_command import _build_claude_command

    assert _model_flag(_build_claude_command(_phase(declared), "hi")) == launched


def test_explicit_allowed_id_is_launched_unchanged() -> None:
    from syn_api._wiring_agent_command import _build_claude_command

    argv = _build_claude_command(_phase(ModelId.CLAUDE_SONNET_5), "hi")
    assert _model_flag(argv) == "claude-sonnet-5"


def test_retired_model_is_refused_at_launch() -> None:
    """A template stored before the deny-list still cannot launch one."""
    from syn_api._wiring_agent_command import _build_claude_command

    phase = _phase(ModelId.CLAUDE_SONNET_4_5)  # constructing it must still work
    with pytest.raises(RetiredModelError, match="claude-sonnet-4-5-20250929"):
        _build_claude_command(phase, "hi")
