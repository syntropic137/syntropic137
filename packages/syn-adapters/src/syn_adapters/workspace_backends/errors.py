"""Shared error types for workspace backend adapters (issue #771 item 7).

`WorkspaceProvisionError` originally lived only in
`syn_adapters.workspace_backends.agentic.adapter` (the Docker-backed
provider). It lives here so error-mapping layers downstream
(`_fail_execution`, `syn execution show`) have one type to match against
instead of a bare `RuntimeError`, importable without pulling in the
agentic adapter module; `agentic/adapter.py` re-exports it for backward
compatibility.
"""

from __future__ import annotations

from enum import StrEnum


class ProvisionFailureReason(StrEnum):
    """Why a workspace could not be provisioned. Stable, machine-readable."""

    PROVIDER_FAILED = "provider_failed"
    IMAGE_VERIFICATION_FAILED = "image_verification_failed"
    # AppArmor is active on the Docker host but the Codex sandbox profile the
    # image needs is not loaded. Fixed by a one-time host step, not a retry.
    APPARMOR_PROFILE_NOT_LOADED = "apparmor_profile_not_loaded"
    # The requested Codex sandbox policy contradicts the image's declaration.
    CODEX_SANDBOX_POLICY_CONFLICT = "codex_sandbox_policy_conflict"
    # A security-relevant Docker host property (e.g. AppArmor) could not be
    # determined. Never treated as "feature absent".
    DOCKER_DETECTION_FAILED = "docker_detection_failed"


class WorkspaceProvisionError(RuntimeError):
    """Raised when workspace provisioning fails or is misconfigured.

    Wraps the underlying error (or a misconfiguration message, e.g. a
    disabled feature flag or an unavailable provider) with enough context
    so downstream error-mapping layers can surface an actionable message
    instead of "Unknown error". ``reason`` classifies it without parsing text.
    """

    reason: ProvisionFailureReason = ProvisionFailureReason.PROVIDER_FAILED


class AppArmorProfileMissingError(WorkspaceProvisionError):
    """The Docker host enforces AppArmor and the Codex sandbox profile is not loaded.

    ``remedy`` is the exact host command that fixes it; see
    docs/deployment/apparmor-codex-sandbox.md.
    """

    reason = ProvisionFailureReason.APPARMOR_PROFILE_NOT_LOADED

    def __init__(self, message: str, *, profile: str, remedy: str) -> None:
        super().__init__(message)
        self.profile = profile
        self.remedy = remedy


class CodexSandboxPolicyConflictError(WorkspaceProvisionError):
    reason = ProvisionFailureReason.CODEX_SANDBOX_POLICY_CONFLICT


class DockerHostDetectionError(WorkspaceProvisionError):
    reason = ProvisionFailureReason.DOCKER_DETECTION_FAILED


__all__ = [
    "AppArmorProfileMissingError",
    "CodexSandboxPolicyConflictError",
    "DockerHostDetectionError",
    "ProvisionFailureReason",
    "WorkspaceProvisionError",
]
