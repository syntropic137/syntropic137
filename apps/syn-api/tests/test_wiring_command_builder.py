"""Regression tests for provider-specific agent command construction.

These pin the DEFAULT sandbox level, which is currently ``danger-full-access``.

That value is unchanged from before #1157, but it is no longer hardcoded: it is
now a per-phase declaration that merely defaults here. A phase wanting LESS
authority declares it and gets it today.

The default stays permissive as a stopgap. ``workspace-write`` was tried in
v0.28.0-beta.5 and broke every codex phase - the deliverable write under
``artifacts/output/`` was denied, so no artifact was produced and the phase
still reported ``completed`` (#1167). See test_codex_sandbox_least_privilege.py.
"""

from __future__ import annotations

import pytest

from syn_api._wiring import (
    _build_agent_command,
    _build_claude_command,
    _build_codex_command,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)

# Without this the whole module collects ZERO under CI's `pytest -m unit`, and
# the gate goes green having run none of it - including the argv pin that
# guards the #964 --tools change.
pytestmark = pytest.mark.unit


def _phase(
    provider: str, model: str = "gpt-5.6", tools: tuple[str, ...] = ("Read", "Bash")
) -> ExecutablePhase:
    return ExecutablePhase(
        phase_id="phase-1",
        name="Agent phase",
        order=1,
        agent_config=AgentConfiguration(
            provider=provider,
            model=model,
            allowed_tools=list(tools),
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
    # Codex declares NO tools here: it cannot restrict by tool name, so a
    # declaration is now refused rather than dropped (#964).
    assert _build_agent_command(_phase("codex", tools=()), "x")[0] == "codex"
    assert _build_agent_command(_phase("claude"), "x")[0] == "claude"


def test_claude_command_argv_is_pinned() -> None:
    """Pins the argv, INCLUDING the #964 change from --allowedTools to --tools.

    This guard caught that change, which is what it is for. The change is
    deliberate: --allowedTools governs auto-approval and, beside
    --dangerously-skip-permissions on the same line, restricted nothing.
    """
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
        "--tools",
        "Read,Bash",
    ]

    assert _build_claude_command(phase, "do the thing") == expected


def test_the_prompt_must_precede_the_variadic_tools_flag() -> None:
    """`--tools` is variadic and GREEDY: it swallows any positional after it.

    Verified against claude 2.1.251 - `claude -p --tools Bash,Read "say ok"`
    fails with "Input must be provided either through stdin or as a prompt
    argument", because the prompt was consumed as a tool name.

    The full-argv pin above would also catch a reordering, but only as an
    opaque list diff. This names the hazard, so a future edit that moves the
    flag earlier fails with the reason rather than with a puzzle.
    """
    argv = _build_claude_command(_phase("claude", model="sonnet"), "do the thing")

    assert argv.index("-p") < argv.index("--tools"), (
        "--tools is greedy; the prompt must be passed before it or it is eaten"
    )
    assert argv[argv.index("-p") + 1] == "do the thing"


def test_the_dispatched_prompt_carries_the_tool_grant() -> None:
    """_build_agent_command adds the harness-neutral grant; the builder does not."""
    phase = _phase("claude", model="sonnet")

    argv = _build_agent_command(phase, "do the thing")
    prompt = argv[argv.index("-p") + 1]

    assert "do the thing" in prompt
    assert "Read" in prompt and "Bash" in prompt
