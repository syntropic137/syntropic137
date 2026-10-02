"""Translate agentic_isolation host-security refusals into typed provision failures.

The isolation layer fails closed when the Docker host cannot run a Codex
sandbox safely. Each refusal maps to one ``WorkspaceProvisionError`` subclass
with a stable ``reason`` so the execution failure names the fix instead of a
generic provider error. Nothing here retries: every case needs an operator.
"""

from __future__ import annotations

from agentic_isolation import (
    AppArmorProfileNotLoadedError,
    CodexSandboxPolicyError,
    DockerDetectionError,
    codex_sandbox_apparmor_profile_path,
)

from syn_adapters.workspace_backends.errors import (
    AppArmorProfileMissingError,
    CodexSandboxPolicyConflictError,
    DockerHostDetectionError,
    WorkspaceProvisionError,
)

#: Where the setup step persists the profile so it loads at every boot.
APPARMOR_PROFILE_DIR = "/etc/apparmor.d"
HOST_SETUP_DOC = "docs/deployment/apparmor-codex-sandbox.md"


def apparmor_remedy() -> str:
    """The exact host command that loads the shipped profile now and at boot."""
    return f"just apparmor-setup  # or: sudo apparmor_parser -r {codex_sandbox_apparmor_profile_path()}"


def host_security_failure(
    error: AppArmorProfileNotLoadedError | CodexSandboxPolicyError | DockerDetectionError,
    execution_id: str,
) -> WorkspaceProvisionError:
    if isinstance(error, AppArmorProfileNotLoadedError):
        remedy = apparmor_remedy()
        return AppArmorProfileMissingError(
            f"Workspace provisioning refused for execution {execution_id}: the Docker host "
            f"enforces AppArmor but profile {error.profile!r} is not loaded, so a Codex "
            f"sandbox cannot start safely. Run on the Docker host: {remedy} "
            f"(see {HOST_SETUP_DOC}).",
            profile=error.profile,
            remedy=remedy,
        )
    if isinstance(error, CodexSandboxPolicyError):
        return CodexSandboxPolicyConflictError(
            f"Workspace provisioning refused for execution {execution_id}: the requested "
            f"Codex sandbox policy contradicts the workspace image: {error}"
        )
    return DockerHostDetectionError(
        f"Workspace provisioning refused for execution {execution_id}: a security-relevant "
        f"Docker host property could not be determined ({error}). Check that `docker info` "
        "succeeds for the API's Docker endpoint."
    )


__all__ = ["APPARMOR_PROFILE_DIR", "apparmor_remedy", "host_security_failure"]
