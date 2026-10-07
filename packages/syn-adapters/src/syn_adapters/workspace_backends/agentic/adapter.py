"""Agentic workspace adapters - thin wrappers around agentic_isolation.

These adapters implement Syn137's domain ports by delegating to the
agentic_isolation library from agentic-workspace. This keeps Syn137
focused on orchestration and observability, not container management.

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

import logging
import os
import shlex
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from agentic_isolation import (
    AppArmorProfileNotLoadedError,
    CodexSandboxPolicyError,
    DockerDetectionError,
    SecurityConfig,
    WorkspaceDockerProvider,
)

from syn_adapters.diagnostics import capture_signal_death
from syn_adapters.workspace_backends.agentic.adapter_copy import (
    check_workspace_health,
    copy_files_from_workspace,
    copy_files_to_workspace,
)
from syn_adapters.workspace_backends.agentic.cpu_hints import with_cpu_hints
from syn_adapters.workspace_backends.agentic.session_store_env import (
    apply_session_store_env,
    deployment_identity,
)

# Re-exported for backward compatibility (issue #771 item 7): the canonical
# definition lives in `syn_adapters.workspace_backends.errors` so it can be
# raised/imported without depending on this Docker-specific module. Existing
# `from ...agentic.adapter import WorkspaceProvisionError` call sites keep
# working unchanged.
from syn_adapters.workspace_backends.agentic.teardown_usage import usage_from_report
from syn_adapters.workspace_backends.errors import WorkspaceProvisionError
from syn_adapters.workspace_backends.exec_status_lost import (
    diagnose_lost_status,
    status_was_lost,
    workspace_container_name,
)
from syn_adapters.workspace_backends.host_security import host_security_failure
from syn_adapters.workspace_backends.image_verification import verify_image_async
from syn_shared.env_constants import (
    ENV_SYN_AGENT_NETWORK,
    ENV_SYN_WORKSPACE_CONTAINER_DIR,
    ENV_SYN_WORKSPACE_HOST_DIR,
)
from syn_shared.settings.workspace_images import DEFAULT_WORKSPACE_IMAGE

if TYPE_CHECKING:
    from collections.abc import Mapping

    from agentic_isolation import AgenticWorkspace

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
        IsolationConfig,
        IsolationHandle,
        WorkspaceUsage,
    )
    from syn_shared.settings.session_store import SessionStoreSettings

logger = logging.getLogger(__name__)

__all__ = ["AgenticIsolationAdapter", "WorkspaceProvisionError"]


#: Where `just` and anything else that writes-then-executes a temp file can do
#: so. `/tmp` is mounted `noexec` by the isolation layer
#: (agentic_isolation/config.py: `--tmpfs=/tmp:rw,noexec,nosuid,size=256m`),
#: alongside `/spool` and `/var/agentic`. That is deliberate hardening and is
#: not something to weaken for a build tool.
#:
#: The consequence was severe and silent: `just` writes a shebang recipe to a
#: temp file and executes it, so EVERY shebang recipe failed with
#: `Permission denied (os error 13)` - including `qa-ci`, which is the gate the
#: verify phase is instructed to run. A phase could spend an hour of model time
#: and then be unable to certify its own work (#1042).
#:
#: Verified inside a running workspace:
#:
#:     $ just shebang-recipe
#:     error: ... execution error: Permission denied (os error 13)
#:     $ TMPDIR=/workspace/.tmp just shebang-recipe
#:     SHEBANG_RAN_OK
#:
#: `/workspace` is writable and executable; `/var/tmp` and `/dev/shm` are not.
_EXECUTABLE_TMPDIR = "/workspace/.tmp"

#: Where tool caches go instead of `$HOME`.
#:
#: WHY (issue #1133). The workspace mounts `/home/agent` as a 128 MB tmpfs
#: (`agentic_isolation/config.py`), and that is `$HOME` - where uv, ruff, npm
#: and node all cache by default. A real verify phase died there:
#:
#:   the workspace's 128 MiB /home/agent tmpfs ran out of space
#:   error: recipe `lint` failed on line 932 with exit code 1
#:
#: `/workspace` is on the container filesystem, which had 157 GB free on the
#: same host. A prompt-level `export` cannot fix this reliably: it lasts for
#: one shell, and the command that fills the disk is usually a dependency
#: install the agent runs before the command carrying the export.
_WORKSPACE_CACHE_ENV: Final[dict[str, str]] = {
    "XDG_CACHE_HOME": "/workspace/.cache",
    "UV_CACHE_DIR": "/workspace/.cache/uv",
    "npm_config_cache": "/workspace/.cache/npm",
}


def _with_executable_tmpdir(environment: Mapping[str, str]) -> dict[str, str]:
    """Point TMPDIR and the tool caches somewhere with room, unless told otherwise.

    A caller-supplied value always wins: these are defaults for the common
    case, not policy. Nothing is created here: this function only builds a
    dict. The caches are created by the tools that use them (`uv`, `npm`), but
    TMPDIR is NOT - `create` makes it, see `_ensure_tmpdir`.
    """
    resolved = dict(environment)
    for key, value in ({"TMPDIR": _EXECUTABLE_TMPDIR} | _WORKSPACE_CACHE_ENV).items():
        if not resolved.get(key):
            resolved[key] = value
    return resolved


def _container_labels(config: IsolationConfig) -> dict[str, str]:
    """Docker labels that let an operator count live containers by owner.

    A workspace provisioned outside a phase has no phase, so it gets no
    `syn.phase_id` label rather than an empty one: `--filter label=syn.phase_id`
    must match only containers that really belong to a phase.
    """
    labels = {
        "syn.execution_id": config.execution_id,
        "syn.workspace_id": config.workspace_id,
    }
    if config.phase_id:
        labels["syn.phase_id"] = config.phase_id
    return labels


class AgenticIsolationAdapter:
    """Implements IsolationBackendPort using agentic_isolation.

    This adapter delegates container lifecycle management to the
    WorkspaceDockerProvider from agentic-workspace.

    Usage:
        adapter = AgenticIsolationAdapter()
        handle = await adapter.create(config)
        result = await adapter.execute(handle, ["python", "script.py"])
        await adapter.destroy(handle)
    """

    def __init__(
        self,
        *,
        default_image: str = DEFAULT_WORKSPACE_IMAGE,
        security: SecurityConfig | None = None,
        workspace_container_dir: str | None = None,
        workspace_host_dir: str | None = None,
        session_store: SessionStoreSettings | None = None,
        capture_source_instance_id: str | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            default_image: Default Docker image for workspaces
            security: Security configuration (defaults to production)
            workspace_container_dir: Path inside orchestrator container (for file I/O)
            workspace_host_dir: Path on Docker host (for volume mounts)
            session_store: Central session-store settings. Defaults to
                ``get_settings().session_store``, which is DISABLED unless
                ``SYN_SESSION_STORE_URL`` is configured.

        When running inside a container, both paths are needed:
        - container_dir: where this process writes files (/workspaces)
        - host_dir: what Docker uses for -v mount (host absolute path)

        Uses env vars SYN_WORKSPACE_CONTAINER_DIR and SYN_WORKSPACE_HOST_DIR if not set.
        """

        self._default_image = default_image
        self._security = security or SecurityConfig.production()

        # Central session store (SeshMagic). Resolved from the settings object
        # rather than os.environ so the credential stays a SecretStr all the way
        # to the point of injection. Disabled by default — see
        # `session_store_env.build_session_store_env`.
        if session_store is None:
            from syn_shared.settings import get_settings

            session_store = get_settings().session_store
        self._session_store = session_store
        self._capture_source_instance_id = capture_source_instance_id

        # Get paths from env or args
        container_dir = workspace_container_dir or os.environ.get(
            ENV_SYN_WORKSPACE_CONTAINER_DIR, "/workspaces"
        )
        host_dir = workspace_host_dir or os.environ.get(ENV_SYN_WORKSPACE_HOST_DIR)

        self._container_base_dir = container_dir
        self._host_base_dir = host_dir  # May be None if same as container dir

        # ISS-43: Use agent-net so containers can reach the shared Envoy proxy
        # but cannot reach the internet directly.
        agent_network = os.environ.get(ENV_SYN_AGENT_NETWORK, "agent-net")

        self._provider = WorkspaceDockerProvider(
            default_image=default_image,
            security=self._security,
            workspace_base_dir=container_dir,
            workspace_host_dir=host_dir,  # For Docker volume mounts
            default_network=agent_network,
        )
        self._workspaces: dict[str, AgenticWorkspace] = {}

    @staticmethod
    def is_available() -> bool:
        """Check if Docker is available."""
        return WorkspaceDockerProvider.is_available()

    def _build_environment(self, config: IsolationConfig) -> dict[str, str]:
        """Build the container environment, including the session-store block."""
        # Remote export remains optional. Controlled workflow launches add the
        # local provider and durable mount after this host-owned contract is built.
        # Caller-supplied capture settings never override configured credentials.
        return apply_session_store_env(
            with_cpu_hints(
                _with_executable_tmpdir(config.environment or {}),
                config.security_policy.cpu_limit_cores,
            ),
            self._session_store,
            execution_id=config.execution_id,
            workspace_id=config.workspace_id,
            workflow_id=config.workflow_id,
            phase_id=config.phase_id,
            # Which Syn137 deployment produced this session. Without it every
            # workspace across dev, beta and prod is indistinguishable in the
            # corpus: the envelope's own origin.environment is the runtime
            # CLASS, which is the same value for all of them.
            deployment=self._deployment_identity(),  # honours the operator override
        )

    def _deployment_identity(self) -> str:
        """``syntropic137__<app_environment>``, or the operator's override.

        Imported locally, matching how session-store settings are resolved above:
        syn_shared settings resolve 1Password at first construction, so importing
        at module scope would make that a side effect of importing the adapter.

        Reads the override off `self._session_store` - the SAME settings object
        `build_expectations` is handed - so the injected value and the expected
        value cannot disagree.
        """
        from syn_shared.settings import get_settings

        return deployment_identity(
            str(get_settings().app_environment),
            self._session_store.display_deployment,
        )

    async def create(self, config: IsolationConfig) -> IsolationHandle:
        """Create an isolated workspace container.

        Args:
            config: Isolation configuration from Syn137 domain

        Returns:
            IsolationHandle for subsequent operations
        """
        from agentic_isolation import ResourceLimits, WorkspaceConfig

        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            IsolationHandle,
        )

        environment = self._build_environment(config)
        from syn_adapters.session_inventory.workspace_capture import apply_workspace_capture

        capture_mounts = (
            apply_workspace_capture(config, self._capture_source_instance_id, environment)
            if self._capture_source_instance_id is not None
            else []
        )

        # Map Syn137 config to agentic_isolation config
        # ISS-43: Network is set on the provider (default_network in __init__),
        # not on WorkspaceConfig. Containers join agent-net to reach the shared
        # Envoy proxy but cannot reach the internet directly.
        #
        # NOTE: the session-store write token is in `environment` only. It must
        # never be copied into `labels` — labels are readable by anyone who can
        # run `docker inspect`.
        image = config.image or self._default_image

        # Supply-chain gate: verify the cosign signature of the exact image
        # reference we are about to run, before any container exists. Raises
        # ImageVerificationError (a WorkspaceProvisionError) on failure, so an
        # unverified image never reaches the provider.
        #
        # The RETURN VALUE is what runs, not `image`. For a digest-pinned
        # registry reference they are the same string; for an explicitly
        # permitted local image the return value is that image's immutable
        # local image ID, so Docker cannot pull or retag something else in
        # between. See image_verification for the full policy.
        image = await verify_image_async(image)

        ws_config = WorkspaceConfig(
            provider="docker",
            image=image,
            working_dir="/workspace",
            environment=environment,
            mounts=capture_mounts,
            labels=_container_labels(config),
            security=self._security,
            limits=ResourceLimits(
                cpu=f"{config.security_policy.cpu_limit_cores:g}",
                memory=f"{config.security_policy.memory_limit_mb}m",
            ),
        )

        # Create workspace via provider — wrap so docker/network failures surface
        # with execution context all the way to the CLI (was "Unknown error").
        try:
            workspace_obj = await self._provider.create(ws_config)
        except (
            AppArmorProfileNotLoadedError,
            CodexSandboxPolicyError,
            DockerDetectionError,
        ) as exc:
            raise host_security_failure(exc, config.execution_id) from exc
        except Exception as exc:
            logger.exception(
                "Workspace provisioning failed (execution=%s, workspace=%s)",
                config.execution_id,
                config.workspace_id,
            )
            raise WorkspaceProvisionError(
                f"Workspace provisioning failed for execution {config.execution_id}: {exc}"
            ) from exc

        await self._ensure_tmpdir(workspace_obj, environment, config.execution_id)

        # Store for later operations
        self._workspaces[workspace_obj.id] = workspace_obj  # type: ignore[arg-type]  # Workspace vs AgenticWorkspace adapter boundary

        logger.info(
            "Created workspace (id=%s, execution=%s)",
            workspace_obj.id,
            config.execution_id,
        )

        return IsolationHandle(
            isolation_id=workspace_obj.id,
            isolation_type="docker",
            proxy_url=None,
            workspace_path="/workspace",
            host_workspace_path=workspace_obj.metadata.get("workspace_dir", ""),
        )

    async def _ensure_tmpdir(
        self, workspace: object, environment: Mapping[str, str], execution_id: str
    ) -> None:
        """Create the workspace's TMPDIR before anything runs in it (PC-120).

        A TMPDIR that does not exist is not a harmless default. Codex's
        linux-sandbox canonicalizes it and PANICS (exit 101):

            failed to resolve synthetic mount registry temp directory
            /workspace/.tmp: No such file or directory (os error 2)

        so a codex phase's sandbox probe refused the workspace. It went
        unnoticed because `skills add` happens to create `$TMPDIR`, and every
        codex phase but the eval verifier declared skills: a phase with none
        failed 5 of 6 runs. Whoever chooses the directory makes it exist, rather
        than relying on an unrelated step to create it first. A failure here is
        a provisioning failure: a workspace whose TMPDIR cannot be made would
        fail later, with a far worse message.
        """
        tmpdir = environment.get("TMPDIR")
        if not tmpdir:
            return
        result = await self._provider.execute(
            workspace,  # type: ignore[arg-type]  # Workspace vs AgenticWorkspace adapter boundary
            shlex.join(["mkdir", "-p", tmpdir]),
        )
        if result.exit_code != 0:
            # The container exists and no caller holds a handle to it yet, so
            # nobody else can reap it.
            await self._provider.destroy(workspace)  # type: ignore[arg-type]  # Workspace vs AgenticWorkspace adapter boundary
            raise WorkspaceProvisionError(
                f"Workspace provisioning failed for execution {execution_id}: "
                f"could not create TMPDIR {tmpdir} (exit {result.exit_code}): "
                f"{(result.stderr or result.stdout or '').strip()[:300] or 'no output'}"
            )

    async def destroy(self, handle: IsolationHandle) -> WorkspaceUsage | None:
        """Destroy an isolated workspace.

        Args:
            handle: Handle from create()

        Returns:
            What the workspace consumed, from the provider's teardown report,
            or None when the provider reported nothing.
        """
        workspace = self._workspaces.pop(handle.isolation_id, None)
        if workspace is None:
            logger.warning("Workspace not found: %s", handle.isolation_id)
            return None

        logger.info("Destroying workspace (id=%s)", handle.isolation_id)
        # `object`: the pinned provider is annotated `-> None`, so pyright
        # cannot check its report against `TeardownReportLike` yet; a field
        # mismatch is logged at runtime by `usage_from_report` instead. Once
        # agentic-workspace types `destroy` against the Protocol, drop this.
        report: object = await self._provider.destroy(workspace)  # type: ignore[arg-type,func-returns-value]  # Workspace vs AgenticWorkspace adapter boundary
        return usage_from_report(report)

    async def execute(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Execute command in workspace.

        Args:
            handle: Handle from create()
            command: Command to execute
            timeout_seconds: Max execution time
            working_directory: Working directory override
            environment: Additional environment variables

        Returns:
            ExecutionResult with exit code, stdout, stderr
        """
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            ExecutionResult,
        )

        workspace = self._workspaces.get(handle.isolation_id)
        if workspace is None:
            return ExecutionResult(
                exit_code=1,
                success=False,
                duration_ms=0.0,
                stderr="Workspace not found",
            )

        # QUOTED join, not a bare one. The provider hands the result to
        # `sh -c`, so every element has to survive as its own argument.
        #
        # `" ".join(...)` silently reassociated them. ["sh", "-c", "test -e X"]
        # became `sh -c test -e X`, which runs `test` with NO operands and
        # therefore always exits 1. The staged-codex-credential check in
        # setup_phase.py is exactly that shape: it reads "credential gone" on
        # every run and its fail-closed branch could never execute. Proven in a
        # container - `sh -c test -e /tmp/exists` exits 1 for a file that
        # exists, `sh -c 'test -e /tmp/exists'` exits 0.
        #
        # shlex.join is identical for simple argv (no metacharacters, nothing
        # to quote) and only differs where the old behaviour was wrong.
        cmd_str = shlex.join(command)

        result = await self._provider.execute(
            workspace,  # type: ignore[arg-type]  # Workspace vs AgenticWorkspace adapter boundary
            cmd_str,
            timeout=float(timeout_seconds) if timeout_seconds else None,
            cwd=working_directory,
            env=environment,
        )

        # THE MOMENT OF DEATH, and the only one there is. Every short command
        # the platform runs in a workspace arrives here - the unpushed-work
        # gate's `git rev-parse`, the `find` over /workspace/repos, the
        # secret-injection setup script - and all three have been lost to a
        # bare `-11` (#1295). Captured HERE rather than by any caller because
        # the reap removes the container moments later and no caller runs
        # before it (#1319).
        signal_death = await capture_signal_death(command, result.exit_code)
        if signal_death is not None:
            logger.error(
                "Command in workspace %s died on a signal:\n%s",
                handle.isolation_id,
                signal_death.describe(),
            )
        # No status AND no output is not an answer, and passed on as-is it
        # reached the operator as "failed ... and printed nothing". Say what
        # the container was doing and whether the deadline had already passed,
        # here, while the container still exists to be asked.
        stderr = result.stderr
        if status_was_lost(result):
            stderr = await diagnose_lost_status(
                workspace_container_name(handle.isolation_id),
                duration_ms=result.duration_ms,
                timeout_seconds=float(timeout_seconds) if timeout_seconds else None,
            )
            logger.error("Command in workspace %s: %s", handle.isolation_id, stderr)
        return ExecutionResult(
            exit_code=result.exit_code,
            success=result.success,
            duration_ms=result.duration_ms,
            stdout=result.stdout,
            stderr=stderr,
            timed_out=result.timed_out,
            signal_death=signal_death,
        )

    async def health_check(self, handle: IsolationHandle) -> bool:
        """Check if workspace is healthy."""
        return check_workspace_health(self._workspaces, handle)

    async def copy_to(
        self,
        handle: IsolationHandle,
        files: list[tuple[str, bytes]],
        base_path: str = "/workspace",
    ) -> None:
        """Copy files into workspace."""
        await copy_files_to_workspace(self._workspaces, self._provider, handle, files, base_path)

    async def copy_from(
        self,
        handle: IsolationHandle,
        patterns: list[str],
        base_path: str = "/workspace",
    ) -> list[tuple[str, bytes]]:
        """Copy files from workspace via mounted volume."""
        return await copy_files_from_workspace(handle, patterns, base_path)
