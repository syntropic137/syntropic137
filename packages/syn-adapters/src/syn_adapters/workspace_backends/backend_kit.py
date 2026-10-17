"""BackendKit: the one composition point for a workspace backend (#1914).

Every decision that differs between backends is made here, once, at wiring,
so no caller coordinates them: which image may run and how it is verified,
whether sessions are captured, which credential policy applies, and the
isolation type reported on the handle. See
docs/research/2026-10-08-remote-executor-e2b.md, decision 3.

Only the Docker kit exists today, and under ``HostCredentials`` it is exactly
the behaviour the Docker adapter had before the kit: capture only when a
capture source instance is configured, cosign verification of every image,
and ``isolation_type="docker"``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from syn_adapters.workspace_backends.errors import WorkspaceProvisionError
from syn_adapters.workspace_backends.image_verification import verify_image_async
from syn_domain.contexts.orchestration import (
    HOST_CREDENTIALS,
    WorkspaceCredentialPolicy,
)
from syn_shared.settings.workspace_images import DEFAULT_WORKSPACE_IMAGE


class CredentialFreeImageError(WorkspaceProvisionError):
    """A credential-free kit was asked to run an image not approved for it."""


@dataclass(frozen=True)
class BackendKit:
    """Everything backend-specific about provisioning a workspace.

    ``credential_free_images`` is the allowlist a ``NoCredentials`` kit may
    run. It is empty unless wiring names one: no stub image is pinned yet
    (that is agentic-workspace work, step H), so today no credential-free kit
    can start - which is the safe answer, not a gap.
    """

    default_image: str = DEFAULT_WORKSPACE_IMAGE
    credential_policy: WorkspaceCredentialPolicy = HOST_CREDENTIALS
    capture_source_instance_id: str | None = None
    isolation_type: str = "docker"
    credential_free_images: frozenset[str] = field(default_factory=frozenset[str])

    def __post_init__(self) -> None:
        self._require_permitted(self.default_image)

    @property
    def captures_sessions(self) -> bool:
        return self.capture_source_instance_id is not None

    async def resolve_image(self, requested: str | None) -> str:
        """The verified image reference to run for a workspace.

        A per-run image under a credential-free kit must be on the allowlist
        too; otherwise a run could swap in an image that expects credentials.
        The return value is what runs (see image_verification).
        """
        image = requested or self.default_image
        self._require_permitted(image)
        return await verify_image_async(image)

    def _require_permitted(self, image: str) -> None:
        if self.credential_policy.supplies_credentials:
            return
        if image not in self.credential_free_images:
            msg = (
                f"A credential-free (NoCredentials) workspace backend refuses image {image!r}: "
                "only an image approved for credential-free runs may start under it "
                f"(approved: {sorted(self.credential_free_images) or 'none'})."
            )
            raise CredentialFreeImageError(msg)
