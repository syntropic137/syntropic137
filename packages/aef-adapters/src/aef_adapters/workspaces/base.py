"""Base class for isolated workspace implementations.

Provides shared functionality for all isolation backends:
- Hook configuration
- Context injection
- Artifact collection
- Lifecycle management

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from aef_adapters.workspaces.types import IsolatedWorkspace, IsolatedWorkspaceConfig
    from aef_shared.settings import IsolationBackend, WorkspaceSecuritySettings


class BaseIsolatedWorkspace(ABC):
    """Abstract base class for isolated workspace implementations.

    Subclasses implement backend-specific isolation:
    - GVisorWorkspace: Docker + gVisor runtime
    - HardenedDockerWorkspace: Docker with security hardening
    - FirecrackerWorkspace: Firecracker MicroVMs
    - E2BWorkspace: E2B cloud sandboxes

    Common functionality (hooks, context, artifacts) is shared here.
    """

    # Override in subclasses
    isolation_backend: ClassVar[IsolationBackend]

    # Default path to agentic-primitives hooks (relative to repo root)
    DEFAULT_HOOKS_PATH: ClassVar[Path] = Path("lib/agentic-primitives/primitives/v1/hooks")

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Check if this backend is available on the current platform.

        Returns:
            True if this backend can be used, False otherwise.
        """
        ...

    @classmethod
    @asynccontextmanager
    async def create(
        cls,
        config: IsolatedWorkspaceConfig,
    ) -> AsyncIterator[IsolatedWorkspace]:
        """Create an isolated workspace as an async context manager.

        Template method that:
        1. Creates the isolation environment
        2. Sets up hooks and configuration
        3. Yields the workspace
        4. Cleans up on exit

        Args:
            config: Isolated workspace configuration

        Yields:
            Configured IsolatedWorkspace ready for agent execution
        """
        # Get security settings (use defaults if not provided)
        security = config.security
        if security is None:
            from aef_shared.settings import WorkspaceSecuritySettings

            security = WorkspaceSecuritySettings()

        # Create the isolation (backend-specific)
        workspace = await cls._create_isolation(config, security)

        try:
            # Mark as started
            workspace.mark_started()

            # Set up directory structure
            await cls._setup_directories(workspace)

            # Copy hooks from agentic-primitives
            await cls._setup_hooks(workspace)

            # Generate settings.json
            await cls._generate_settings(workspace)

            yield workspace

        finally:
            # Mark as terminated
            workspace.mark_terminated()

            # Clean up the isolation (backend-specific)
            await cls._destroy_isolation(workspace)

            # Clean up local files if configured
            if config.base_config.cleanup_on_exit:
                shutil.rmtree(workspace.path, ignore_errors=True)

    @classmethod
    @abstractmethod
    async def _create_isolation(
        cls,
        config: IsolatedWorkspaceConfig,
        security: WorkspaceSecuritySettings,
    ) -> IsolatedWorkspace:
        """Create the isolation environment (backend-specific).

        This method should:
        1. Create the container/VM/sandbox
        2. Return an IsolatedWorkspace with appropriate IDs set

        Args:
            config: Workspace configuration
            security: Security settings to apply

        Returns:
            IsolatedWorkspace with isolation IDs populated
        """
        ...

    @classmethod
    @abstractmethod
    async def _destroy_isolation(cls, workspace: IsolatedWorkspace) -> None:
        """Destroy the isolation environment (backend-specific).

        This method should:
        1. Stop the container/VM/sandbox
        2. Clean up any resources

        Args:
            workspace: The workspace to destroy
        """
        ...

    @classmethod
    async def _setup_directories(cls, workspace: IsolatedWorkspace) -> None:
        """Create the workspace directory structure."""
        directories = [
            workspace.path / ".claude" / "hooks" / "handlers",
            workspace.path / ".claude" / "hooks" / "validators" / "security",
            workspace.path / ".claude" / "hooks" / "validators" / "prompt",
            workspace.path / ".agentic" / "analytics",
            workspace.path / ".context",
            workspace.path / "output",
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    @classmethod
    async def _setup_hooks(cls, workspace: IsolatedWorkspace) -> None:
        """Copy hooks from agentic-primitives to the workspace."""
        # Find hooks source
        hooks_source = cls._find_hooks_source(workspace.path)

        if hooks_source and hooks_source.exists():
            # Copy handlers
            handlers_src = hooks_source / "handlers"
            handlers_dst = workspace.path / ".claude" / "hooks" / "handlers"
            if handlers_src.exists():
                for handler in handlers_src.glob("*.py"):
                    shutil.copy2(handler, handlers_dst / handler.name)
                    (handlers_dst / handler.name).chmod(0o755)

            # Copy validators
            validators_src = hooks_source / "validators"
            validators_dst = workspace.path / ".claude" / "hooks" / "validators"
            if validators_src.exists():
                for subdir in validators_src.iterdir():
                    if subdir.is_dir():
                        dst_subdir = validators_dst / subdir.name
                        dst_subdir.mkdir(parents=True, exist_ok=True)
                        for validator in subdir.glob("*.py"):
                            shutil.copy2(validator, dst_subdir / validator.name)
        else:
            # Create minimal stub handlers if hooks not found
            await cls._create_stub_handlers(workspace)

    @classmethod
    def _find_hooks_source(cls, workspace_dir: Path) -> Path | None:
        """Find the agentic-primitives hooks directory."""
        search_paths = [
            workspace_dir.parent.parent
            / "lib"
            / "agentic-primitives"
            / "primitives"
            / "v1"
            / "hooks",
            Path.cwd() / "lib" / "agentic-primitives" / "primitives" / "v1" / "hooks",
        ]

        for path in search_paths:
            if path.exists():
                return path

        return None

    @classmethod
    async def _create_stub_handlers(cls, workspace: IsolatedWorkspace) -> None:
        """Create minimal stub handlers when agentic-primitives not found.

        WARNING: These stubs ALLOW ALL operations without validation.
        They are suitable for testing only. In production, proper hooks
        from agentic-primitives should always be available.
        """
        # Log warning about using stubs (per ADR-004)
        app_env = os.getenv("APP_ENVIRONMENT", "development").lower()
        if app_env not in ("test", "testing"):
            logger.warning(
                "Creating stub handlers that ALLOW ALL operations. "
                "This bypasses security validation. Ensure agentic-primitives "
                "hooks are available at: lib/agentic-primitives/primitives/v1/hooks"
            )

        handlers_dir = workspace.path / ".claude" / "hooks" / "handlers"

        # Pre-tool-use stub (allow all)
        pre_tool_use = handlers_dir / "pre-tool-use.py"
        pre_tool_use.write_text('''#!/usr/bin/env python3
"""Stub pre-tool-use handler - allows all tool calls."""
import json
import sys

def main():
    sys.stdin.read()
    print(json.dumps({"decision": "allow"}))

if __name__ == "__main__":
    main()
''')
        pre_tool_use.chmod(0o755)

        # Post-tool-use stub (no-op)
        post_tool_use = handlers_dir / "post-tool-use.py"
        post_tool_use.write_text('''#!/usr/bin/env python3
"""Stub post-tool-use handler - no-op logging."""
import sys

def main():
    sys.stdin.read()

if __name__ == "__main__":
    main()
''')
        post_tool_use.chmod(0o755)

        # User-prompt stub (allow all)
        user_prompt = handlers_dir / "user-prompt.py"
        user_prompt.write_text('''#!/usr/bin/env python3
"""Stub user-prompt handler - allows all prompts."""
import json
import sys

def main():
    sys.stdin.read()
    print(json.dumps({"decision": "allow"}))

if __name__ == "__main__":
    main()
''')
        user_prompt.chmod(0o755)

    @classmethod
    async def _generate_settings(cls, workspace: IsolatedWorkspace) -> None:
        """Generate .claude/settings.json for hook configuration."""
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/handlers/pre-tool-use.py",
                                "timeout": 10,
                            }
                        ],
                    }
                ],
                "PostToolUse": [
                    {
                        "matcher": "*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/handlers/post-tool-use.py",
                                "timeout": 10,
                            }
                        ],
                    }
                ],
                "UserPromptSubmit": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/handlers/user-prompt.py",
                                "timeout": 5,
                            }
                        ],
                    }
                ],
            }
        }

        settings_path = workspace.path / ".claude" / "settings.json"
        settings_path.write_text(json.dumps(settings, indent=2))

    @classmethod
    async def inject_context(
        cls,
        workspace: IsolatedWorkspace,
        files: list[tuple[Path, bytes]],
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Inject context files into the workspace.

        Args:
            workspace: The workspace to inject into
            files: List of (relative_path, content) tuples
            metadata: Optional metadata to write as context.json
        """
        context_dir = workspace.context_dir
        context_dir.mkdir(parents=True, exist_ok=True)

        for rel_path, content in files:
            file_path = context_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)

        if metadata:
            metadata_path = context_dir / "context.json"
            metadata_path.write_text(json.dumps(metadata, indent=2, default=str))

    @classmethod
    async def collect_artifacts(
        cls,
        workspace: IsolatedWorkspace,
        output_patterns: list[str] | None = None,
    ) -> list[tuple[Path, bytes]]:
        """Collect artifacts from the workspace output directory.

        Args:
            workspace: The workspace to collect from
            output_patterns: Glob patterns to match (default: all files)

        Returns:
            List of (relative_path, content) tuples
        """
        output_dir = workspace.output_dir
        if not output_dir.exists():
            return []

        patterns = output_patterns or ["**/*"]
        artifacts: list[tuple[Path, bytes]] = []

        for pattern in patterns:
            for file_path in output_dir.glob(pattern):
                if file_path.is_file():
                    rel_path = file_path.relative_to(output_dir)
                    content = file_path.read_bytes()
                    artifacts.append((rel_path, content))

        return artifacts

    @classmethod
    async def health_check(cls, workspace: IsolatedWorkspace) -> bool:
        """Verify the isolation is working correctly.

        Subclasses can override to add backend-specific health checks.

        Args:
            workspace: The workspace to check

        Returns:
            True if the workspace is healthy, False otherwise
        """
        # Default: check that the workspace path exists and is accessible
        return workspace.path.exists() and workspace.is_running

    @classmethod
    @abstractmethod
    async def execute_command(
        cls,
        workspace: IsolatedWorkspace,
        command: list[str],
        timeout: int | None = None,
        cwd: str | None = None,
    ) -> tuple[int, str, str]:
        """Execute a command inside the isolated workspace.

        Args:
            workspace: The workspace to execute in
            command: Command and arguments to run
            timeout: Optional timeout in seconds
            cwd: Working directory (relative to workspace root)

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        ...

    @classmethod
    async def execute_streaming(
        cls,
        workspace: IsolatedWorkspace,
        command: list[str],
        timeout: int | None = None,
        cwd: str | None = None,
    ) -> AsyncIterator[str]:
        """Execute command and stream stdout lines.

        This is used for long-running agent executions where we want
        to stream JSONL events from the agent runner.

        Args:
            workspace: The workspace to execute in
            command: Command and arguments to run
            timeout: Maximum execution time in seconds
            cwd: Working directory (relative to workspace root)

        Yields:
            Lines from stdout (JSONL events from agent runner)

        Raises:
            TimeoutError: If execution exceeds timeout
            RuntimeError: If execution fails

        Example:
            async for line in cls.execute_streaming(
                workspace,
                ["python", "-m", "aef_agent_runner"],
                timeout=300,
            ):
                event = json.loads(line)
                handle_agent_event(event)
        """
        import asyncio

        # Get container ID
        container_id = workspace.container_id or workspace.vm_id or workspace.sandbox_id
        if not container_id:
            raise RuntimeError("No container ID available for streaming execution")

        # Build docker exec command
        exec_cmd = ["docker", "exec", "-i", container_id]
        if cwd:
            exec_cmd.extend(["-w", cwd])
        exec_cmd.extend(command)

        process = await asyncio.create_subprocess_exec(
            *exec_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            async with asyncio.timeout(timeout) if timeout else contextlib.nullcontext():
                if process.stdout:
                    async for line in process.stdout:
                        yield line.decode().rstrip("\n")
        except TimeoutError:
            process.kill()
            raise

        await process.wait()
        if process.returncode != 0:
            stderr_content = ""
            if process.stderr:
                stderr_content = (await process.stderr.read()).decode()
            raise RuntimeError(
                f"Command failed with exit code {process.returncode}: {stderr_content}"
            )

    @classmethod
    async def request_cancellation(
        cls,
        workspace: IsolatedWorkspace,
    ) -> None:
        """Request graceful cancellation of running agent.

        Writes .cancel file to workspace which agent runner polls for.

        Args:
            workspace: The workspace to cancel
        """
        container_id = workspace.container_id or workspace.vm_id or workspace.sandbox_id
        if not container_id:
            return

        import asyncio

        # Create .cancel file in workspace
        cmd = ["docker", "exec", container_id, "touch", "/workspace/.cancel"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
