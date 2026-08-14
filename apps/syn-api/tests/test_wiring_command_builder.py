"""Regression tests for provider-specific agent command construction."""

from __future__ import annotations

from syn_api._wiring import (
    _build_agent_command,
    _build_claude_command,
    _build_codex_command,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)


def _phase(provider: str, model: str = "gpt-5.6") -> ExecutablePhase:
    return ExecutablePhase(
        phase_id="phase-1",
        name="Agent phase",
        order=1,
        agent_config=AgentConfiguration(
            provider=provider,
            model=model,
            allowed_tools=("Read", "Bash"),
        ),
    )


def test_codex_command_passes_actual_model_and_prompt_as_individual_args() -> None:
    assert _build_codex_command("do the thing", "gpt-5.6") == [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        "danger-full-access",
        "--skip-git-repo-check",
        "--model",
        "gpt-5.6",
        "do the thing",
    ]


def test_codex_command_omits_model_option_when_model_is_not_provided() -> None:
    assert _build_codex_command("do the thing", None) == [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        "danger-full-access",
        "--skip-git-repo-check",
        "do the thing",
    ]


def test_codex_command_omits_claude_alias_model() -> None:
    # AgentConfiguration.model defaults to "haiku" (a Claude alias); codex rejects
    # Claude model ids, so it must NOT be forwarded - codex uses its account default.
    assert "--model" not in _build_codex_command("do the thing", "haiku")
    assert "--model" not in _build_codex_command("do the thing", "sonnet")
    assert "--model" not in _build_codex_command("do the thing", "claude-opus-4")
    # a genuine codex / openai model id IS forwarded.
    assert _build_codex_command("do the thing", "o3")[-3:] == ["--model", "o3", "do the thing"]


def test_codex_command_via_domain_default_model_omits_model_flag() -> None:
    """Regression (#788 follow-up, PR #795): a codex phase that omits
    `model:` must resolve to a command with NO `--model` flag - codex runs
    model-unforced (its own account default), not `--model codex` (which
    an earlier fix synthesized and which is not a real codex model id).
    """
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseDefinition,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
        _build_agent_config_from_phase,
    )
    from syn_shared.agents import AgentProvider

    phase_def = PhaseDefinition(
        phase_id="p1",
        name="p",
        order=1,
        prompt_template="x",
        provider=AgentProvider.CODEX,
    )
    cfg = _build_agent_config_from_phase(phase_def)
    assert cfg.model is None

    cmd = _build_codex_command("do the thing", cfg.model)
    assert cmd == [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        "danger-full-access",
        "--skip-git-repo-check",
        "do the thing",
    ]
    assert "--model" not in cmd


def test_agent_command_dispatches_on_provider_string() -> None:
    assert _build_agent_command(_phase("codex"), "x")[0] == "codex"
    assert _build_agent_command(_phase("claude"), "x")[0] == "claude"


def test_claude_command_argv_is_unchanged() -> None:
    phase = _phase("claude", model="sonnet")
    expected = [
        "claude",
        "--model",
        "sonnet",
        "--verbose",
        "--output-format",
        "stream-json",
        "--dangerously-skip-permissions",
        "-p",
        "do the thing",
        "--allowedTools",
        "Read",
        "--allowedTools",
        "Bash",
    ]

    assert _build_claude_command(phase, "do the thing") == expected
    assert _build_agent_command(phase, "do the thing") == expected
