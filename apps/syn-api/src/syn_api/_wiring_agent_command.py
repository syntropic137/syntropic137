"""Agent invocation for a phase: the workspace prompt and the harness argv.

Split out of ``_wiring`` (#185): pure functions with no adapter state, handed
to ``WorkflowExecutionProcessor`` as its ``prompt_builder`` and
``command_builder``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_api._codex_command import (
    UnsupportedToolPolicyError,
    _build_codex_command,
    _resolve_sandbox,
    apply_tool_policy_to_prompt,
)
from syn_shared.agents import (
    AgentProvider,
    UnsupportedAgentProviderError,
    require_executable_provider,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

logger = logging.getLogger(__name__)


def _build_claude_command(
    phase: ExecutablePhase,
    prompt: str,
) -> list[str]:
    """Build the Claude CLI command for agent execution."""
    # `AgentConfiguration.model` is typed `str | None`, but a claude-provider
    # phase always resolves a concrete model (the persisted template default,
    # else syn_shared.agents.DEFAULT_CLAUDE_MODEL), so `None` here would
    # indicate a construction bug elsewhere, not a real "unset" case worth
    # silently tolerating - fail loudly instead of forwarding `--model None`.
    model = phase.agent_config.model
    if model is None:
        msg = (
            f"Claude phase '{phase.phase_id}' resolved to a None model - "
            "AgentConfiguration.model should always default to a claude "
            "alias for provider='claude'."
        )
        raise ValueError(msg)
    cmd = [
        "claude",
        "--model",
        model,
        "--verbose",
        "--output-format",
        "stream-json",
        "--dangerously-skip-permissions",
        "-p",
        prompt,
    ]

    # `--tools` is AVAILABILITY; `--allowedTools` is auto-approval. We emitted
    # the second while the field is named and documented as the first, and the
    # command already carries --dangerously-skip-permissions, so auto-approving
    # was a no-op twice over: a phase declaring three tools could use all of
    # them (issue #964). Verified against claude 2.1.251:
    #   --tools <tools...>  Specify the list of available tools from the
    #                       built-in set. Use "" to disable all tools ...
    #
    # ONE flag with a comma-joined list, not the flag repeated. `--tools` is
    # VARIADIC (`<tools...>`), which has two consequences:
    #
    #   1. Repeating it keeps only the last occurrence, so the flag-per-tool
    #      form would have restricted every phase to its last-declared tool.
    #   2. It is GREEDY - it swallows any positional that follows it. Verified
    #      against claude 2.1.251:
    #        $ claude -p --tools Bash,Read "say ok"
    #        Error: Input must be provided either through stdin or as a prompt
    #               argument when using --print
    #      The prompt was eaten as a tool name.
    #
    # ORDERING IS THEREFORE LOAD-BEARING: `-p <prompt>` must come BEFORE
    # `--tools`. Moving this extend() earlier breaks every claude phase, with
    # an error that names stdin rather than argument order. Pinned by
    # test_the_prompt_must_precede_the_variadic_tools_flag.
    if phase.agent_config.allowed_tools:
        cmd.extend(["--tools", ",".join(phase.agent_config.allowed_tools)])

    return cmd


def _build_agent_command(
    phase: ExecutablePhase,
    prompt: str,
) -> list[str]:
    """Build the command selected by the phase provider.

    Exhaustive on purpose: every known provider is named, and anything else
    raises. The previous ``return _build_claude_command(...)`` fall-through
    meant an unknown or removed provider - a stored ``claude-interactive``
    template rehydrated from history, say - quietly ran as headless Claude and
    reported success.
    """
    provider = require_executable_provider(
        phase.agent_config.provider,
        phase_id=phase.phase_id,
    )
    # Every harness carries the grant in the prompt; only claude can also
    # enforce it on the command line.
    scoped_prompt = apply_tool_policy_to_prompt(prompt, phase.agent_config.allowed_tools)
    if provider is AgentProvider.CODEX:
        if phase.agent_config.allowed_tools:
            raise UnsupportedToolPolicyError(
                provider=str(provider),
                phase_id=phase.phase_id,
                declared=list(phase.agent_config.allowed_tools),
            )
        return _build_codex_command(
            scoped_prompt,
            phase.agent_config.model,
            _resolve_sandbox(phase.agent_config.sandbox, phase_id=phase.phase_id),
        )
    if provider is AgentProvider.CLAUDE:
        return _build_claude_command(phase, scoped_prompt)
    raise UnsupportedAgentProviderError(provider, phase_id=phase.phase_id)


def _owner_repo_from_url(url: str | None) -> str:
    """Extract owner/repo from a GitHub HTTPS URL. Empty string if not a github URL."""
    if not url:
        return ""
    stripped = url.rstrip("/").removesuffix(".git")
    parts = stripped.split("/")
    if len(parts) >= 5 and parts[2] == "github.com":
        return f"{parts[3]}/{parts[4]}"
    return ""


def _substitute_builtins(
    template: str,
    execution_id: str,
    workflow_id: str,
    repo_url: str | None,
) -> str:
    """Layer 1: Replace built-in variables in the prompt template."""
    result = template.replace("{{execution_id}}", execution_id)
    result = result.replace("{{workflow_id}}", workflow_id)
    result = result.replace("{{repo_url}}", repo_url or "")
    # {{repository}} is a deprecated single-repo convenience -- derived from the
    # primary repo's URL as owner/repo. Tracked for removal in #715.
    # Multi-repo workflows should use {{repos}} (CSV of HTTPS URLs) or discover
    # repos from /workspace/repos/ at runtime instead.
    if "{{repository}}" in result:
        logger.warning(
            "Workflow %s uses deprecated {{repository}} template variable. "
            "It will be removed in a future release. Migrate to /workspace/repos/ "
            "discovery (single-repo) or {{repos}} (multi-repo). "
            "Track: https://github.com/syntropic137/syntropic137/issues/715",
            workflow_id,
        )
        result = result.replace("{{repository}}", _owner_repo_from_url(repo_url))
    return result


def _substitute_inputs(
    template: str,
    phase: ExecutablePhase,
    inputs: Mapping[str, object] | None,
    phase_outputs: dict[str, str],
) -> str:
    """Layers 2a-2d: Replace workflow inputs, phase inputs, outputs, and $ARGUMENTS."""
    result = template

    # Layer 2a: Workflow inputs
    if inputs:
        for key, value in inputs.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))

    # Layer 2b: Phase-level static inputs
    for phase_input in phase.inputs:
        if phase_input.value is not None:
            result = result.replace(f"{{{{{phase_input.name}}}}}", phase_input.value)

    # Layer 2c: Phase outputs inline
    for pid, content in phase_outputs.items():
        result = result.replace(f"{{{{{pid}}}}}", content[:2000])

    # Layer 2d: $ARGUMENTS substitution (ISS-211 CC command pattern)
    from syn_domain.contexts.orchestration import TASK_PLACEHOLDER

    task = (inputs or {}).get("task", "")
    result = result.replace(TASK_PLACEHOLDER, str(task))

    return result


def _build_context_appendix(phase_outputs: dict[str, str]) -> str:
    """Layer 3: Build the context appendix from previous phase outputs."""
    parts = ["\n## Context from Previous Phases"]
    for pid, content in phase_outputs.items():
        parts.append(f"\n### Phase {pid}\n{content[:2000]}")
    return "\n".join(parts)


async def _build_workspace_prompt(
    phase: ExecutablePhase,
    execution_id: str,
    workflow_id: str,
    repo_url: str | None,
    phase_outputs: dict[str, str],
    inputs: Mapping[str, object] | None = None,
) -> str:
    """Build the workspace prompt for a phase.

    Substitution layers (in order):
    1. Built-in variables: {{execution_id}}, {{workflow_id}}, {{repo_url}}
    2a. Workflow inputs: {{key}} → value from inputs dict
    2b. Phase-level static inputs: {{name}} → value from phase definition
    2c. Phase outputs: {{phase-id}} → previous phase artifact content (inline)
    2d. $ARGUMENTS → task string from inputs["task"]
    3. Context appendix: previous phase outputs appended as fallback section
    """
    from syn_domain.contexts.orchestration import render_workspace_prompt

    phase_prompt = _substitute_builtins(phase.prompt_template, execution_id, workflow_id, repo_url)
    phase_prompt = _substitute_inputs(phase_prompt, phase, inputs, phase_outputs)

    # The preamble describes the workspace this phase actually got, so it is
    # rendered per phase rather than shared: `clone_repos: false` means no
    # checkout, and telling that agent the repository is on disk is what made
    # the merged gate unusable (#1187).
    prompt_parts = [
        render_workspace_prompt(clone_repos=phase.clone_repos),
        f"\n## Task\n{phase_prompt}",
    ]

    if phase_outputs:
        prompt_parts.append(_build_context_appendix(phase_outputs))

    return "\n".join(prompt_parts)
