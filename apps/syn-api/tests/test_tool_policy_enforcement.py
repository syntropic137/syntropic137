"""Phase tool/token declarations must restrict, or refuse (issue #964).

Three members of ONE class - per-phase agent config that is parsed, displayed,
and dropped before execution:

1. ``allowed_tools`` was forwarded to ``--allowedTools``, which governs
   AUTO-APPROVAL, not availability. With ``--dangerously-skip-permissions`` on
   the same command line it is a no-op twice over.
2. ``max_tokens`` reached no command builder - and cannot, because NEITHER CLI
   has a token-cap flag (verified against claude 2.1.251 and codex 0.147.0).
3. Codex has no tool-name concept at all, only ``-s <SANDBOX_MODE>``, so a
   declaration that scopes tools means something different per provider.
"""

from __future__ import annotations

import pytest

from syn_shared.agents import AgentProvider
from syn_shared.tools import ToolName

pytestmark = pytest.mark.unit


def _phase(tools=None, provider=AgentProvider.CLAUDE, model="haiku"):
    from syn_domain.contexts.orchestration._shared.ExecutionValueObjects import (
        AgentConfiguration,
        ExecutablePhase,
    )

    return ExecutablePhase(
        phase_id="p1",
        name="p1",
        order=0,
        prompt_template="do the thing",
        agent_config=AgentConfiguration(
            provider=provider,
            model=model,
            allowed_tools=list(tools or []),
        ),
    )


class TestAvailabilityNotAutoApproval:
    def test_declared_tools_emit_the_availability_flag(self) -> None:
        from syn_api._wiring import _build_claude_command

        cmd = _build_claude_command(_phase([ToolName.BASH, ToolName.READ]), "prompt")

        assert "--tools" in cmd, "must restrict availability, not merely auto-approve"
        assert "--allowedTools" not in cmd

    def test_the_tool_list_is_one_comma_separated_argument(self) -> None:
        """`--tools` takes one list; repeating the flag keeps only the last."""
        from syn_api._wiring import _build_claude_command

        cmd = _build_claude_command(_phase([ToolName.BASH, ToolName.READ]), "prompt")

        assert cmd.count("--tools") == 1
        assert cmd[cmd.index("--tools") + 1] == "Bash,Read"

    def test_an_undeclared_phase_is_left_unrestricted(self) -> None:
        """Omitting the field must not silently become "no tools at all"."""
        from syn_api._wiring import _build_claude_command

        cmd = _build_claude_command(_phase([]), "prompt")

        assert "--tools" not in cmd


class TestCodexRefusesWhatItCannotHonour:
    def test_codex_rejects_a_tool_declaration_rather_than_ignoring_it(self) -> None:
        """Silently discarding a declared control is how you believe you have one."""
        from syn_api._wiring import UnsupportedToolPolicyError, _build_agent_command

        with pytest.raises(UnsupportedToolPolicyError) as exc:
            _build_agent_command(_phase([ToolName.BASH], provider=AgentProvider.CODEX), "p")

        assert "codex" in str(exc.value).lower()

    def test_codex_without_a_declaration_still_runs(self) -> None:
        from syn_api._wiring import _build_agent_command

        cmd = _build_agent_command(_phase([], provider=AgentProvider.CODEX), "p")

        assert cmd[:2] == ["codex", "exec"]


class TestPromptCarriesTheGrant:
    """The only harness-NEUTRAL mechanism, and it needs no CLI support."""

    def test_declared_tools_are_named_in_the_prompt(self) -> None:
        from syn_api._wiring import apply_tool_policy_to_prompt

        prompt = apply_tool_policy_to_prompt("do the thing", [ToolName.BASH, ToolName.READ])

        assert "do the thing" in prompt
        assert "Bash" in prompt
        assert "Read" in prompt

    def test_an_undeclared_phase_gets_an_unmodified_prompt(self) -> None:
        from syn_api._wiring import apply_tool_policy_to_prompt

        assert apply_tool_policy_to_prompt("do the thing", []) == "do the thing"

    def test_the_grant_does_not_name_tools_that_were_not_declared(self) -> None:
        from syn_api._wiring import apply_tool_policy_to_prompt

        prompt = apply_tool_policy_to_prompt("x", [ToolName.READ])

        assert "Bash" not in prompt
