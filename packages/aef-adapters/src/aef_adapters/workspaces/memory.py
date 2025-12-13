"""InMemoryWorkspace - fast workspace for tests.

This workspace stores files in memory without touching the filesystem.
It is designed for unit tests where speed is critical and isolation
is not required (tests run in a controlled environment).

Unlike LocalWorkspace (which also has no isolation but uses temp files),
InMemoryWorkspace is purely in-memory for maximum speed.

See ADR-023: Workspace-First Execution Model
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class TestEnvironmentRequiredError(Exception):
    """Raised when InMemoryWorkspace is used outside test environment."""

    pass


def _assert_test_environment() -> None:
    """Assert we're in test environment - InMemoryWorkspace is TEST-ONLY.

    Raises:
        TestEnvironmentRequiredError: If APP_ENVIRONMENT is not 'test' or 'testing'
    """
    app_env = os.getenv("APP_ENVIRONMENT", "development").lower()

    if app_env in ("test", "testing"):
        return  # OK

    raise TestEnvironmentRequiredError(
        f"InMemoryWorkspace cannot be used in '{app_env}' environment. "
        f"InMemoryWorkspace is for TESTS ONLY.\n\n"
        f"Use WorkspaceRouter.create() for isolated execution:\n"
        f"  from aef_adapters.workspaces import get_workspace_router\n"
        f"  router = get_workspace_router()\n"
        f"  async with router.create(config) as workspace:\n"
        f"      ...\n\n"
        f"See ADR-023: Workspace-First Execution Model"
    )


@dataclass
class InMemoryFile:
    """A file stored in memory."""

    content: bytes
    mode: int = 0o644


@dataclass
class InMemoryWorkspace:
    """In-memory workspace for tests - no filesystem access.

    This workspace is designed for maximum test speed. All files are
    stored in a dictionary, commands are mocked.

    WARNING: This provides NO ISOLATION and is TEST ONLY.

    Example:
        # In tests (APP_ENVIRONMENT=test):
        async with InMemoryWorkspace.create(config) as workspace:
            await workspace.write_file("test.txt", b"hello")
            content = await workspace.read_file("test.txt")
            assert content == b"hello"
    """

    workspace_id: str
    session_id: str
    files: dict[str, InMemoryFile] = field(default_factory=dict)
    command_history: list[tuple[list[str], int, str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # IsolatedWorkspace protocol properties
    @property
    def isolation_id(self) -> str:
        """Return the workspace ID."""
        return self.workspace_id

    @property
    def workspace_path(self) -> Path:
        """Return a virtual path (not real filesystem)."""
        return Path(f"/virtual/{self.workspace_id}")

    @classmethod
    @asynccontextmanager
    async def create(
        cls,
        config: Any,  # IsolatedWorkspaceConfig or WorkspaceConfig
    ) -> AsyncIterator[InMemoryWorkspace]:
        """Create an in-memory workspace - TEST ONLY.

        Args:
            config: Workspace configuration

        Yields:
            InMemoryWorkspace instance

        Raises:
            TestEnvironmentRequiredError: If not in test environment
        """
        _assert_test_environment()

        import uuid

        # Extract session_id from config
        session_id = getattr(config, "session_id", None)
        if session_id is None:
            base_config = getattr(config, "base_config", None)
            if base_config:
                session_id = getattr(base_config, "session_id", str(uuid.uuid4()))
            else:
                session_id = str(uuid.uuid4())

        workspace = cls(
            workspace_id=f"mem-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
        )

        # Pre-create standard directories (as empty markers)
        workspace.files[".claude/settings.json"] = InMemoryFile(b'{"hooks": {}}')
        workspace.files[".context/.gitkeep"] = InMemoryFile(b"")
        workspace.files["output/.gitkeep"] = InMemoryFile(b"")

        yield workspace

        # No cleanup needed - it's all in memory

    async def write_file(self, path: str, content: bytes, mode: int = 0o644) -> None:
        """Write a file to the in-memory filesystem."""
        self.files[path] = InMemoryFile(content=content, mode=mode)

    async def read_file(self, path: str) -> bytes:
        """Read a file from the in-memory filesystem."""
        if path not in self.files:
            raise FileNotFoundError(f"File not found: {path}")
        return self.files[path].content

    async def file_exists(self, path: str) -> bool:
        """Check if a file exists."""
        return path in self.files

    async def list_files(self, pattern: str = "*") -> list[str]:
        """List files matching a pattern."""
        import fnmatch

        return [p for p in self.files if fnmatch.fnmatch(p, pattern)]

    async def execute_command(
        self,
        command: list[str],
        _timeout: int | None = None,
        _cwd: str | None = None,
    ) -> tuple[int, str, str]:
        """Mock command execution - records command and returns success.

        For tests, you can override this behavior by setting
        workspace.command_responses before calling.

        Args:
            command: The command to execute
            _timeout: Ignored in mock (kept for interface compatibility)
            _cwd: Ignored in mock (kept for interface compatibility)

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        # Record the command
        result = (0, "", "")  # Default: success with no output
        self.command_history.append((command, *result))
        return result

    @classmethod
    async def inject_context(
        cls,
        workspace: InMemoryWorkspace,
        files: list[tuple[Path, bytes]],
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Inject context files into the workspace."""
        for path, content in files:
            await workspace.write_file(f".context/{path}", content)

        if metadata:
            import json

            await workspace.write_file(
                ".context/context.json",
                json.dumps(metadata, default=str).encode(),
            )

    @classmethod
    async def collect_artifacts(
        cls,
        workspace: InMemoryWorkspace,
        patterns: list[str] | None = None,
    ) -> list[tuple[Path, bytes]]:
        """Collect artifacts from the output directory."""
        import fnmatch

        patterns = patterns or ["*"]
        artifacts: list[tuple[Path, bytes]] = []

        for path, file in workspace.files.items():
            if path.startswith("output/"):
                rel_path = path[7:]  # Remove "output/" prefix
                for pattern in patterns:
                    if fnmatch.fnmatch(rel_path, pattern):
                        artifacts.append((Path(rel_path), file.content))
                        break

        return artifacts

    @classmethod
    def is_available(cls) -> bool:
        """Check if InMemoryWorkspace is available (always True in tests)."""
        app_env = os.getenv("APP_ENVIRONMENT", "development").lower()
        return app_env in ("test", "testing")
