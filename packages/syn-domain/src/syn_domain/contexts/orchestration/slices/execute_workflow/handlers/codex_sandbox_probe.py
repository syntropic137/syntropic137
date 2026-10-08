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

A timeout is not that failure (PC-126): it says the host was too loaded to
answer, nothing about the image or AppArmor. It is retried once - the probe
runs `true` and changes nothing - and a second timeout is recorded as a
transient provision timeout, so a resume clears it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    ProvisionStep,
    ProvisionStepTimeoutError,
)
from syn_shared.agents import AgentProvider, PhaseSandbox
from syn_shared.settings import get_settings

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

#: Attempts a timed-out probe gets in total (PC-126). Any other exit is an
#: answer about the sandbox and is never retried.
_PROBE_ATTEMPTS: Final = 2


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
    timeout_seconds = get_settings().codex_sandbox_probe_timeout_seconds
    for _ in range(_PROBE_ATTEMPTS):
        result = await workspace.execute(
            ["codex", "sandbox", "-c", f'sandbox_mode="{config.sandbox}"', "--", "true"],
            timeout_seconds=timeout_seconds,
            working_directory="/workspace",
        )
        if not result.timed_out:
            break
    else:
        raise ProvisionStepTimeoutError(
            ProvisionStep.CODEX_SANDBOX_PROBE,
            subject=f"phase {phase.phase_id!r}, sandbox {config.sandbox!r}",
            timeout_seconds=timeout_seconds,
            attempts=_PROBE_ATTEMPTS,
        )
    if result.exit_code != 0:
        raise CodexSandboxUnavailableError(
            phase.phase_id, config.sandbox, result.exit_code, result.stderr or result.stdout or ""
        )
