"""BackendKit: the one composition point for a workspace backend (#1914).

Every decision that differs between backends is made here, once, at wiring,
so no caller coordinates them: which image may run and how it is verified,
whether sessions are captured, which credential policy applies, and the
isolation type reported on the handle. See
docs/research/2026-10-08-remote-executor-e2b.md, decision 3.

Under ``HostCredentials`` the Docker kit is exactly the behaviour the Docker
adapter had before the kit: capture only when a capture source instance is
configured, cosign verification of every image, and ``isolation_type="docker"``.

The E2B kit (#1915, :meth:`BackendKit.e2b`) is the second, and is shipped dark.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.errors import WorkspaceProvisionError
from syn_adapters.workspace_backends.image_verification import verify_image_async
from syn_domain.contexts.orchestration import (
    HOST_CREDENTIALS,
    NO_CREDENTIALS,
    WorkspaceCredentialPolicy,
)
from syn_shared.settings.workspace_images import DEFAULT_WORKSPACE_IMAGE

if TYPE_CHECKING:
    from agentic_isolation import MountConfig

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
    )


class CredentialFreeImageError(WorkspaceProvisionError):
    """A credential-free kit was asked to run an image not approved for it."""


class WorkspaceCapacityError(WorkspaceProvisionError):
    """A workspace asked for more CPU or memory than its backend can give it."""


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
    #: Whether an image is cosign-verified before it runs. Only a backend whose
    #: "image" is not an OCI reference turns this off (see :meth:`e2b`).
    verifies_images: bool = True
    #: The most CPU and memory one workspace may get, when the backend sizes
    #: workspaces itself rather than per request. None: no ceiling.
    max_cpu_cores: float | None = None
    max_memory_mb: int | None = None

    def __post_init__(self) -> None:
        self._require_permitted(self.default_image)

    @classmethod
    def e2b(cls, template: str, *, cpu_count: int, memory_mb: int) -> BackendKit:
        """The E2B kit: one template, no host credentials, no capture (#1915).

        The E2B provider refuses credential bindings and host mounts, so this
        kit is ``NoCredentials`` and never captures. Its one approved
        "image" is the template, which is the credential-free allowlist the
        Docker kit leaves empty; a per-run image is therefore refused rather
        than silently ignored. A template is not an OCI reference, so there is
        nothing to cosign-verify here: the image was verified when the
        template was built (agentic-workspace ``build_template`` takes the
        verified digest). E2B sizes a sandbox by its template, so a workspace
        asking for more than the template has is refused. The sandbox's disk
        is not on this host; files come back through the provider, as on every
        backend (#1913).
        """
        return cls(
            default_image=template,
            credential_policy=NO_CREDENTIALS,
            isolation_type="e2b",
            credential_free_images=frozenset({template}),
            verifies_images=False,
            max_cpu_cores=float(cpu_count),
            max_memory_mb=memory_mb,
        )

    @property
    def captures_sessions(self) -> bool:
        return self.capture_source_instance_id is not None

    def capture_mounts(
        self, config: IsolationConfig, environment: dict[str, str]
    ) -> list[MountConfig]:
        """The capture strategy: mounts for this workspace, adding capture env in place.

        Captures only when a capture source instance is configured - the
        condition the Docker adapter applied before the kit, unchanged.
        """
        if self.capture_source_instance_id is None:
            return []
        from syn_adapters.session_inventory.workspace_capture import apply_workspace_capture

        return apply_workspace_capture(config, self.capture_source_instance_id, environment)

    async def resolve_image(self, requested: str | None) -> str:
        """The verified image reference to run for a workspace.

        A per-run image under a credential-free kit must be on the allowlist
        too; otherwise a run could swap in an image that expects credentials.
        The return value is what runs (see image_verification).
        """
        image = requested or self.default_image
        self._require_permitted(image)
        return await verify_image_async(image) if self.verifies_images else image

    def require_fits(self, cpu_cores: float, memory_mb: int) -> None:
        """Refuse a workspace this backend could only run smaller than asked."""
        too_much = [
            f"{asked} {unit} (at most {ceiling})"
            for asked, ceiling, unit in (
                (cpu_cores, self.max_cpu_cores, "CPU cores"),
                (memory_mb, self.max_memory_mb, "MB of memory"),
            )
            if ceiling is not None and asked > ceiling
        ]
        if too_much:
            msg = (
                f"The {self.isolation_type} workspace backend cannot give a workspace "
                + " and ".join(too_much)
            )
            raise WorkspaceCapacityError(msg)

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
