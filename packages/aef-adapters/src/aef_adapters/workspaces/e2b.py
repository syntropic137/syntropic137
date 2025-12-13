"""E2B cloud sandbox workspace - managed cloud isolation for overflow.

E2B (e2b.dev) provides managed cloud sandboxes that can be used for:
- Overflow capacity when local resources are exhausted
- macOS/Windows development where local isolation is limited
- High-scale deployments without infrastructure management

E2B sandboxes provide:
- Full Linux VM isolation
- Persistent filesystem within session
- Network access (configurable)
- Pre-built templates with common tools

Requirements:
- E2B API key (https://e2b.dev)
- Network access to E2B API

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, ClassVar

from aef_adapters.workspaces.base import BaseIsolatedWorkspace
from aef_adapters.workspaces.types import IsolatedWorkspace, IsolatedWorkspaceConfig
from aef_shared.settings import IsolationBackend

if TYPE_CHECKING:
    from pathlib import Path

    import aiohttp

    from aef_shared.settings import WorkspaceSecuritySettings


class E2BWorkspace(BaseIsolatedWorkspace):
    """E2B cloud sandbox workspace for managed isolation.

    E2B provides managed cloud sandboxes that can be used when:
    - Local resources are exhausted (overflow)
    - Strong isolation is needed on platforms without KVM
    - Infrastructure management should be offloaded

    Advantages:
    - No local infrastructure needed
    - Works on any platform (macOS, Windows, Linux)
    - Managed security and isolation
    - Fast sandbox creation (~1-2s)

    Disadvantages:
    - Requires network access
    - Per-minute pricing
    - API key required
    - Latency to cloud

    Prerequisites:
    1. E2B account and API key
    2. Network access to api.e2b.dev
    3. Pre-configured sandbox template (optional)

    Usage:
        async with E2BWorkspace.create(config) as workspace:
            exit_code, stdout, stderr = await E2BWorkspace.execute_command(
                workspace, ["python", "script.py"]
            )
    """

    isolation_backend: ClassVar[IsolationBackend] = IsolationBackend.CLOUD

    # E2B API configuration
    API_BASE_URL: ClassVar[str] = "https://api.e2b.dev"
    DEFAULT_TEMPLATE: ClassVar[str] = "base"  # E2B base template

    @classmethod
    def is_available(cls) -> bool:
        """Check if E2B API key is configured.

        Returns:
            True if E2B API key is available in settings.
        """
        from aef_shared.settings import get_settings

        try:
            settings = get_settings()
            api_key = settings.workspace.cloud_api_key
            return api_key is not None
        except Exception:
            # Also check environment variable directly
            return bool(os.environ.get("AEF_WORKSPACE_CLOUD_API_KEY"))

    @classmethod
    async def _create_isolation(
        cls,
        config: IsolatedWorkspaceConfig,
        security: WorkspaceSecuritySettings,
    ) -> IsolatedWorkspace:
        """Create an E2B cloud sandbox.

        Args:
            config: Workspace configuration
            security: Security settings to apply

        Returns:
            IsolatedWorkspace with sandbox_id populated
        """
        import tempfile
        from pathlib import Path as LocalPath

        from aef_shared.settings import get_settings

        settings = get_settings()
        workspace_settings = settings.workspace

        # Get API key
        api_key = workspace_settings.cloud_api_key
        if api_key is None:
            raise RuntimeError("E2B API key not configured")

        api_key_value = api_key.get_secret_value()

        # Create local workspace directory for artifact staging
        if config.base_config.base_dir:
            workspace_dir = config.base_config.base_dir / config.session_id
        else:
            workspace_dir = LocalPath(tempfile.mkdtemp(prefix=f"aef-e2b-{config.session_id}-"))

        workspace_dir.mkdir(parents=True, exist_ok=True)

        # Create E2B sandbox via API
        template = workspace_settings.cloud_template
        sandbox_id = await cls._create_sandbox(
            api_key=api_key_value,
            template=template,
            timeout=security.max_execution_time,
        )

        return IsolatedWorkspace(
            path=workspace_dir,
            config=config.base_config,
            isolation_backend=cls.isolation_backend,
            sandbox_id=sandbox_id,
            security=security,
        )

    @classmethod
    async def _create_sandbox(
        cls,
        *,
        api_key: str,
        template: str,
        timeout: int,
    ) -> str:
        """Create an E2B sandbox via API.

        Args:
            api_key: E2B API key
            template: Sandbox template name
            timeout: Sandbox timeout in seconds

        Returns:
            Sandbox ID

        Raises:
            RuntimeError: If sandbox creation fails
        """
        import aiohttp

        url = f"{cls.API_BASE_URL}/sandboxes"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "template": template,
            "timeout": timeout,
            "metadata": {
                "source": "aef",
            },
        }

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(url, headers=headers, json=payload) as response,
            ):
                if response.status != 201:
                    error_text = await response.text()
                    raise RuntimeError(
                        f"E2B sandbox creation failed: {response.status} - {error_text}"
                    )

                data = await response.json()
                return data["sandboxId"]

        except aiohttp.ClientError as e:
            raise RuntimeError(f"E2B API request failed: {e}") from e

    @classmethod
    async def _destroy_isolation(cls, workspace: IsolatedWorkspace) -> None:
        """Terminate the E2B sandbox.

        Args:
            workspace: The workspace to destroy
        """
        if not workspace.sandbox_id:
            return

        from aef_shared.settings import get_settings

        try:
            settings = get_settings()
            api_key = settings.workspace.cloud_api_key
            if api_key is None:
                return

            await cls._kill_sandbox(
                api_key=api_key.get_secret_value(),
                sandbox_id=workspace.sandbox_id,
            )
        except Exception:
            # Log but don't fail - sandbox may already be gone
            pass

    @classmethod
    async def _kill_sandbox(cls, *, api_key: str, sandbox_id: str) -> None:
        """Kill an E2B sandbox via API.

        Args:
            api_key: E2B API key
            sandbox_id: Sandbox to kill
        """
        import aiohttp

        url = f"{cls.API_BASE_URL}/sandboxes/{sandbox_id}"
        headers = {
            "Authorization": f"Bearer {api_key}",
        }

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.delete(url, headers=headers) as response,
            ):
                # 204 = success, 404 = already gone
                if response.status not in (204, 404):
                    pass  # Log warning but don't fail
        except aiohttp.ClientError:
            pass  # Network error, sandbox may be gone

    @classmethod
    async def execute_command(
        cls,
        workspace: IsolatedWorkspace,
        command: list[str],
        timeout: int | None = None,
        cwd: str | None = None,
    ) -> tuple[int, str, str]:
        """Execute a command inside the E2B sandbox.

        Uses E2B's process API to run commands.

        Args:
            workspace: The workspace to execute in
            command: Command and arguments to run
            timeout: Optional timeout in seconds
            cwd: Working directory (relative to sandbox root)

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        if not workspace.sandbox_id:
            raise RuntimeError("Workspace sandbox not running")

        from aef_shared.settings import get_settings

        settings = get_settings()
        api_key = settings.workspace.cloud_api_key
        if api_key is None:
            raise RuntimeError("E2B API key not configured")

        return await cls._run_process(
            api_key=api_key.get_secret_value(),
            sandbox_id=workspace.sandbox_id,
            command=command,
            cwd=cwd or "/home/user",
            timeout=timeout,
        )

    @classmethod
    async def _run_process(
        cls,
        *,
        api_key: str,
        sandbox_id: str,
        command: list[str],
        cwd: str,
        timeout: int | None,
    ) -> tuple[int, str, str]:
        """Run a process in E2B sandbox via API.

        Args:
            api_key: E2B API key
            sandbox_id: Sandbox ID
            command: Command and arguments
            cwd: Working directory
            timeout: Optional timeout

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        import aiohttp

        url = f"{cls.API_BASE_URL}/sandboxes/{sandbox_id}/processes"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "cmd": command[0],
            "args": command[1:] if len(command) > 1 else [],
            "cwd": cwd,
            "timeout": timeout or 300,
        }

        try:
            async with aiohttp.ClientSession() as session:  # noqa: SIM117
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        return (-1, "", f"E2B process failed: {response.status} - {error_text}")

                    data = await response.json()

                    # Wait for process to complete
                    process_id = data.get("processId")
                    if process_id:
                        return await cls._wait_for_process(
                            session, api_key, sandbox_id, process_id, timeout
                        )

                    # Immediate result
                    return (
                        data.get("exitCode", 0),
                        data.get("stdout", ""),
                        data.get("stderr", ""),
                    )

        except TimeoutError:
            return (-1, "", f"Command timed out after {timeout} seconds")
        except aiohttp.ClientError as e:
            return (-1, "", f"E2B API request failed: {e}")

    @classmethod
    async def _wait_for_process(
        cls,
        session: aiohttp.ClientSession,
        api_key: str,
        sandbox_id: str,
        process_id: str,
        timeout: int | None,
    ) -> tuple[int, str, str]:
        """Wait for an E2B process to complete.

        Args:
            session: aiohttp session
            api_key: E2B API key
            sandbox_id: Sandbox ID
            process_id: Process ID to wait for
            timeout: Maximum wait time

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        import aiohttp

        url = f"{cls.API_BASE_URL}/sandboxes/{sandbox_id}/processes/{process_id}/wait"
        headers = {
            "Authorization": f"Bearer {api_key}",
        }

        wait_timeout = timeout or 300

        try:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=wait_timeout + 5),
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    return (-1, "", f"E2B process wait failed: {error_text}")

                data = await response.json()
                return (
                    data.get("exitCode", 0),
                    data.get("stdout", ""),
                    data.get("stderr", ""),
                )

        except TimeoutError:
            return (-1, "", f"Process wait timed out after {wait_timeout}s")

    @classmethod
    async def health_check(cls, workspace: IsolatedWorkspace) -> bool:
        """Verify the E2B sandbox is healthy.

        Args:
            workspace: The workspace to check

        Returns:
            True if sandbox is running and responsive
        """
        if not workspace.sandbox_id or not workspace.is_running:
            return False

        # Try to run a simple command
        try:
            exit_code, _, _ = await cls.execute_command(
                workspace,
                ["true"],
                timeout=10,
            )
            return exit_code == 0
        except Exception:
            return False

    @classmethod
    async def upload_file(
        cls,
        workspace: IsolatedWorkspace,
        local_path: Path,
        remote_path: str,
    ) -> None:
        """Upload a file to the E2B sandbox.

        Args:
            workspace: The workspace
            local_path: Local file path
            remote_path: Path in sandbox
        """
        if not workspace.sandbox_id:
            raise RuntimeError("Workspace sandbox not running")

        from pathlib import Path as LocalPath

        from aef_shared.settings import get_settings

        settings = get_settings()
        api_key = settings.workspace.cloud_api_key
        if api_key is None:
            raise RuntimeError("E2B API key not configured")

        await cls._upload_file(
            api_key=api_key.get_secret_value(),
            sandbox_id=workspace.sandbox_id,
            local_path=LocalPath(local_path),
            remote_path=remote_path,
        )

    @classmethod
    async def _upload_file(
        cls,
        *,
        api_key: str,
        sandbox_id: str,
        local_path: Path,
        remote_path: str,
    ) -> None:
        """Upload a file to E2B sandbox via API.

        Args:
            api_key: E2B API key
            sandbox_id: Sandbox ID
            local_path: Local file path
            remote_path: Path in sandbox
        """
        from pathlib import Path as LocalPath

        import aiohttp

        url = f"{cls.API_BASE_URL}/sandboxes/{sandbox_id}/files"
        headers = {
            "Authorization": f"Bearer {api_key}",
        }

        content = LocalPath(local_path).read_bytes()

        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field(
                "file",
                content,
                filename=LocalPath(local_path).name,
            )
            form.add_field("path", remote_path)

            async with session.post(url, headers=headers, data=form) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise RuntimeError(f"File upload failed: {error_text}")

    @classmethod
    async def download_file(
        cls,
        workspace: IsolatedWorkspace,
        remote_path: str,
        local_path: Path,
    ) -> None:
        """Download a file from the E2B sandbox.

        Args:
            workspace: The workspace
            remote_path: Path in sandbox
            local_path: Local file path
        """
        if not workspace.sandbox_id:
            raise RuntimeError("Workspace sandbox not running")

        from pathlib import Path as LocalPath

        from aef_shared.settings import get_settings

        settings = get_settings()
        api_key = settings.workspace.cloud_api_key
        if api_key is None:
            raise RuntimeError("E2B API key not configured")

        content = await cls._download_file(
            api_key=api_key.get_secret_value(),
            sandbox_id=workspace.sandbox_id,
            remote_path=remote_path,
        )

        LocalPath(local_path).write_bytes(content)

    @classmethod
    async def _download_file(
        cls,
        *,
        api_key: str,
        sandbox_id: str,
        remote_path: str,
    ) -> bytes:
        """Download a file from E2B sandbox via API.

        Args:
            api_key: E2B API key
            sandbox_id: Sandbox ID
            remote_path: Path in sandbox

        Returns:
            File contents as bytes
        """
        import urllib.parse

        import aiohttp

        encoded_path = urllib.parse.quote(remote_path, safe="")
        url = f"{cls.API_BASE_URL}/sandboxes/{sandbox_id}/files/{encoded_path}"
        headers = {
            "Authorization": f"Bearer {api_key}",
        }

        async with (
            aiohttp.ClientSession() as session,
            session.get(url, headers=headers) as response,
        ):
            if response.status != 200:
                error_text = await response.text()
                raise RuntimeError(f"File download failed: {error_text}")

            return await response.read()
