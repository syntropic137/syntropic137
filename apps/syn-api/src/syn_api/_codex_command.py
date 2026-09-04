"""Building the ``codex exec`` argv for a phase.

Split out of ``_wiring`` so the authority a codex phase receives lives in one
small, readable place rather than inside a 1600-line wiring module. The
sandbox level is the security-relevant part of this file: it used to be a
hardcoded ``danger-full-access`` for every codex phase (#1157, #1161).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeGuard

from syn_shared.agents import (
    CODEX_SANDBOX_FLAGS,
    DEFAULT_PHASE_SANDBOX,
    ModelAlias,
    PhaseSandbox,
    UnsupportedPhaseSandboxError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

# Claude CLI model aliases (the AgentConfiguration.model default is "haiku").
# Codex rejects these ("model not supported when using Codex with a ChatGPT
# account"), so we must NOT forward a Claude model to `codex exec` - codex uses
# its own account default instead. TODO(#780): resolve/validate a real codex
# model for accurate cost labelling on codex phases.
_CLAUDE_MODEL_ALIASES = frozenset(ModelAlias)


def _is_codex_model(model: str | None) -> TypeGuard[str]:
    """True only for a model id worth forwarding to `codex exec --model`."""
    if model is None:
        return False
    lowered = model.lower()
    return lowered not in _CLAUDE_MODEL_ALIASES and not lowered.startswith("claude")


class UnsupportedToolPolicyError(ValueError):
    """A phase declared tools the selected harness cannot restrict.

    Raised rather than ignored. Codex expresses policy as a SANDBOX MODE
    (read-only / workspace-write / danger-full-access) and has no tool-name
    concept at all - verified against codex 0.147.0, which exposes no tool
    flag of any kind. Translating a tool allowlist into a sandbox mode is
    lossy in both directions: an allowlist says nothing about filesystem
    scope, and a sandbox says nothing about which tools exist.

    Accepting the declaration and dropping it would mean a workflow that
    scopes tools silently means something different depending on
    ``agent.provider``, which is worse than not scoping at all. Believing you
    have a control you do not have is the failure this issue exists to remove.
    """

    def __init__(self, provider: str, phase_id: str, declared: list[str]) -> None:
        super().__init__(
            f"phase {phase_id!r} declares allowed_tools {declared!r}, but provider "
            f"{provider!r} cannot restrict tools: codex expresses policy as a sandbox "
            f"mode, not a tool list. Remove allowed_tools from this phase, or run it "
            f"on the claude provider."
        )
        self.provider = provider
        self.phase_id = phase_id
        self.declared = declared


_TOOL_GRANT_TEMPLATE = """{prompt}

## Tool policy

You have been granted exactly these tools for this phase: {tools}.

Do not use any other tool. If the task appears to require a tool you were not
granted, stop and say so rather than reaching for one - the omission is the
phase author's deliberate scoping, not an oversight."""


def apply_tool_policy_to_prompt(prompt: str, allowed_tools: Sequence[str]) -> str:
    """Name the declared tools in the prompt itself.

    The ONLY harness-neutral mechanism here: it needs no CLI support, so it
    works identically on claude and codex, and it is the whole of the
    behavioural benefit on a harness that cannot enforce anything.

    Advisory, not enforcement - an agent can ignore it. It is layered UNDER
    `--tools` on claude rather than instead of it, and never presented as a
    security boundary on its own.
    """
    if not allowed_tools:
        return prompt
    return _TOOL_GRANT_TEMPLATE.format(prompt=prompt, tools=", ".join(allowed_tools))


def _resolve_sandbox(declared: str | None, *, phase_id: str) -> PhaseSandbox:
    """Map a phase's declared sandbox level onto a known member.

    An unknown value raises instead of falling back, because silently
    downgrading an unrecognised level hands the phase whatever the default
    happens to be - which is the class of failure this exists to close.
    """
    if declared is None:
        return DEFAULT_PHASE_SANDBOX
    try:
        return PhaseSandbox(declared)
    except ValueError:
        raise UnsupportedPhaseSandboxError(declared, phase_id=phase_id) from None


def _build_codex_command(
    prompt: str,
    model: str | None,
    sandbox: PhaseSandbox = DEFAULT_PHASE_SANDBOX,
) -> list[str]:
    """Build the Codex CLI command for agent execution.

    A codex phase inherits the domain default model ("haiku", a Claude alias)
    unless the YAML sets one. We only forward `--model` when it is a genuine
    codex/OpenAI model id; otherwise codex selects its ChatGPT-account default.

    The sandbox level comes from the phase, never from a constant here. It was
    hardcoded to ``danger-full-access`` for every codex phase, which is how a
    verify phase came to merge, commit and push the change it then certified
    (#1157, #1161).
    """
    cmd = [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        CODEX_SANDBOX_FLAGS[sandbox],
        "--skip-git-repo-check",
    ]
    if _is_codex_model(model):
        cmd.extend(["--model", model])
    cmd.append(prompt)
    return cmd
