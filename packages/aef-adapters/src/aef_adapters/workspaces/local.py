"""LocalWorkspace - file-based workspace implementation.

WARNING: LocalWorkspace provides NO ISOLATION. It runs agents directly on the
host filesystem. This is for TESTING and LOCAL DEVELOPMENT ONLY.

For production, use the isolated backends via WorkspaceRouter:
- GVisorWorkspace (Docker + gVisor)
- HardenedDockerWorkspace (Docker with security hardening)
- FirecrackerWorkspace (MicroVMs)
- E2BWorkspace (Cloud sandboxes)

See ADR-004: Environment Configuration (mock objects policy)
See ADR-021: Isolated Workspace Architecture

Creates temporary directories with:
- .claude/settings.json for hook configuration
- .claude/hooks/ with handlers from agentic-primitives
- .agentic/analytics/ for event output
- .context/ for injected context
- output/ for agent outputs
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from aef_adapters.agents.agentic_types import Workspace, WorkspaceConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class NonIsolatedWorkspaceError(Exception):
    """Raised when LocalWorkspace is used outside test/development environment."""

    pass


def _assert_non_production_environment() -> None:
    """Assert we're not in production - LocalWorkspace has NO isolation.

    LocalWorkspace runs agents directly on the host without any containerization
    or sandboxing. It should NEVER be used in production environments.

    Raises:
        NonIsolatedWorkspaceError: If APP_ENVIRONMENT is 'production' or 'staging'
    """
    app_env = os.getenv("APP_ENVIRONMENT", "development").lower()
    if app_env in ("production", "staging", "prod", "stg"):
        raise NonIsolatedWorkspaceError(
            f"LocalWorkspace provides NO ISOLATION and cannot be used in {app_env}. "
            f"Use WorkspaceRouter with isolated backends (GVisor, Docker, Firecracker, E2B) "
            f"for production deployments. See ADR-021."
        )
    if app_env not in ("test", "testing", "development", "dev", "local"):
        logger.warning(
            "LocalWorkspace provides NO ISOLATION. "
            "Consider using WorkspaceRouter for isolated agent execution. "
            f"Current APP_ENVIRONMENT: {app_env}"
        )


class LocalWorkspace:
    """File-based workspace in temporary directories.

    WARNING: This provides NO ISOLATION. For production use WorkspaceRouter.

    Creates a workspace with hooks from agentic-primitives.

    Example:
        # For testing only:
        config = WorkspaceConfig(session_id="my-session")
        async with LocalWorkspace.create(config) as workspace:
            # workspace.path contains:
            # - .claude/settings.json (hook config)
            # - .claude/hooks/handlers/ (from agentic-primitives)
            # - .claude/hooks/validators/ (from agentic-primitives)
            await agent.execute(task, workspace, config)

        # For production - use isolated backends:
        from aef_adapters.workspaces import WorkspaceRouter
        router = WorkspaceRouter()
        async with router.create(config) as workspace:
            ...
    """

    # Default path to agentic-primitives hooks (relative to repo root)
    DEFAULT_HOOKS_PATH: ClassVar[Path] = Path("lib/agentic-primitives/primitives/v1/hooks")

    @classmethod
    @asynccontextmanager
    async def create(cls, config: WorkspaceConfig) -> AsyncIterator[Workspace]:
        """Create a workspace as an async context manager.

        WARNING: LocalWorkspace provides NO ISOLATION. Agents run directly on the
        host with full filesystem and network access. This is suitable for:
        - Unit tests
        - Integration tests
        - Local development

        For production, use WorkspaceRouter which provides isolated backends.

        Args:
            config: Workspace configuration

        Yields:
            Configured Workspace ready for agent execution

        Raises:
            NonIsolatedWorkspaceError: If used in production environment
        """
        # Check we're not in production - LocalWorkspace has no isolation!
        _assert_non_production_environment()

        # Create temp directory
        base_dir = config.base_dir
        base_dir.mkdir(parents=True, exist_ok=True)

        workspace_dir = Path(
            tempfile.mkdtemp(
                prefix=f"workspace-{config.session_id}-",
                dir=base_dir,
            )
        )

        try:
            # Set up directory structure
            await cls._setup_directories(workspace_dir)

            # Copy hooks from agentic-primitives
            await cls._setup_hooks(workspace_dir, config)

            # Generate settings.json
            await cls._generate_settings(workspace_dir)

            # Create workspace object
            workspace = Workspace(path=workspace_dir, config=config)

            yield workspace

        finally:
            if config.cleanup_on_exit:
                shutil.rmtree(workspace_dir, ignore_errors=True)

    @classmethod
    async def _setup_directories(cls, workspace_dir: Path) -> None:
        """Create the workspace directory structure."""
        directories = [
            workspace_dir / ".claude" / "hooks" / "handlers",
            workspace_dir / ".claude" / "hooks" / "validators" / "security",
            workspace_dir / ".claude" / "hooks" / "validators" / "prompt",
            workspace_dir / ".agentic" / "analytics",
            workspace_dir / ".context",
            workspace_dir / "output",
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    @classmethod
    async def _setup_hooks(cls, workspace_dir: Path, config: WorkspaceConfig) -> None:
        """Copy hooks from agentic-primitives to the workspace."""
        # Determine hooks source (config override or auto-discover)
        hooks_source = config.hooks_source or cls._find_hooks_source(workspace_dir)

        if hooks_source and hooks_source.exists():
            # Copy handlers
            handlers_src = hooks_source / "handlers"
            handlers_dst = workspace_dir / ".claude" / "hooks" / "handlers"
            if handlers_src.exists():
                for handler in handlers_src.glob("*.py"):
                    shutil.copy2(handler, handlers_dst / handler.name)
                    # Make executable
                    (handlers_dst / handler.name).chmod(0o755)

            # Copy validators
            validators_src = hooks_source / "validators"
            validators_dst = workspace_dir / ".claude" / "hooks" / "validators"
            if validators_src.exists():
                for subdir in validators_src.iterdir():
                    if subdir.is_dir():
                        dst_subdir = validators_dst / subdir.name
                        dst_subdir.mkdir(parents=True, exist_ok=True)
                        for validator in subdir.glob("*.py"):
                            shutil.copy2(validator, dst_subdir / validator.name)
        else:
            # Create minimal stub handlers if hooks not found
            await cls._create_stub_handlers(workspace_dir)

    @classmethod
    def _find_hooks_source(cls, workspace_dir: Path) -> Path | None:
        """Find the agentic-primitives hooks directory."""
        # Search upward for the hooks
        search_paths = [
            # Relative to workspace (for worktrees)
            workspace_dir.parent.parent
            / "lib"
            / "agentic-primitives"
            / "primitives"
            / "v1"
            / "hooks",
            # Standard location from repo root
            Path.cwd() / "lib" / "agentic-primitives" / "primitives" / "v1" / "hooks",
        ]

        for path in search_paths:
            if path.exists():
                return path

        return None

    @classmethod
    async def _create_stub_handlers(cls, workspace_dir: Path) -> None:
        """Create minimal stub handlers when agentic-primitives not found.

        WARNING: These stubs ALLOW ALL operations without validation.
        They are suitable for testing only. In production, proper hooks
        from agentic-primitives should always be available.
        """
        # Log warning about using stubs
        app_env = os.getenv("APP_ENVIRONMENT", "development").lower()
        if app_env not in ("test", "testing"):
            logger.warning(
                "Creating stub handlers that ALLOW ALL operations. "
                "This is insecure for production. Ensure agentic-primitives "
                "hooks are available at: lib/agentic-primitives/primitives/v1/hooks"
            )

        handlers_dir = workspace_dir / ".claude" / "hooks" / "handlers"

        # Pre-tool-use stub (allow all)
        pre_tool_use = handlers_dir / "pre-tool-use.py"
        pre_tool_use.write_text('''#!/usr/bin/env python3
"""Stub pre-tool-use handler - allows all tool calls."""
import json
import sys

def main():
    # Read input (not used in stub)
    sys.stdin.read()
    # Allow all
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
    # No output required

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
    async def _generate_settings(cls, workspace_dir: Path) -> None:
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

        settings_path = workspace_dir / ".claude" / "settings.json"
        settings_path.write_text(json.dumps(settings, indent=2))

    @classmethod
    async def inject_context(
        cls,
        workspace: Workspace,
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

        # Write files
        for rel_path, content in files:
            file_path = context_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)

        # Write metadata if provided
        if metadata:
            metadata_path = context_dir / "context.json"
            metadata_path.write_text(json.dumps(metadata, indent=2, default=str))

    @classmethod
    async def collect_artifacts(
        cls,
        workspace: Workspace,
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
