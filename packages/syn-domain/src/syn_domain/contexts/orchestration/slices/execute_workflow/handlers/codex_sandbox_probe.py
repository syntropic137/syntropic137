"""Prove a codex phase's sandbox runs before the agent does (#1434).

Codex enforces ``read-only``/``workspace-write`` with bubblewrap, which runs in
a workspace only when agentic-workspace started it with the Codex sandbox
policy. That policy is chosen by the image's ``agentic.codex_cli_version``
label, so an operator-supplied image without the label starts without it.
Codex then exits 0 with every command failed, and the phase is recorded as
completed having done nothing.

So the guarantee is measured, not inferred: the same live probe
``syn-delegate`` runs before every launch, in the same mode and directory the
agent will get. A failure stops provisioning with a reason, before tokens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syn_shared.agents import AgentProvider, PhaseSandbox

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

_PROBE_TIMEOUT_SECONDS: Final = 60


class CodexSandboxUnavailableError(RuntimeError):
    """The workspace cannot run the codex sandbox level the phase declared."""

    def __init__(self, phase_id: str, sandbox: str, exit_code: int, output: str) -> None:
        self.exit_code = exit_code
        super().__init__(
            f"Phase {phase_id!r} declares agent.sandbox={sandbox!r}, but codex's sandbox "
            f"does not run in this workspace (probe exit {exit_code}): "
            f"{output.strip()[:300] or 'no output'}. The workspace image must carry the "
            "agentic.codex_cli_version label so agentic-workspace applies its Codex "
            "sandbox policy, and on AppArmor hosts the agentic-codex-sandbox profile "
            "must be loaded (just apparmor-setup). Refusing to run the phase, because "
            "codex would exit 0 with every command failed."
        )


async def require_codex_sandbox(workspace: ManagedWorkspace, phase: ExecutablePhase) -> None:
    """Raise unless a codex phase's declared sandbox level actually runs here."""
    config = phase.agent_config
    if config.provider != AgentProvider.CODEX or config.sandbox == PhaseSandbox.FULL_ACCESS:
        return
    result = await workspace.execute(
        ["codex", "sandbox", "-c", f'sandbox_mode="{config.sandbox}"', "--", "true"],
        timeout_seconds=_PROBE_TIMEOUT_SECONDS,
        working_directory="/workspace",
    )
    if result.exit_code != 0:
        raise CodexSandboxUnavailableError(
            phase.phase_id, config.sandbox, result.exit_code, result.stderr or result.stdout or ""
        )
