"""Port for what a command Phase needs of its Workspace (ADR-078 D3).

Run one step to its end with a bounded output tail, write the Phase's report,
and stop a running step on cancel. `ManagedWorkspace` satisfies it; the
handler depends on this, not on the adapter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from syn_domain.contexts.orchestration._shared.command_phase import BoundedCommandResult

__all__ = ["CommandWorkspacePort"]


class CommandWorkspacePort(Protocol):
    """A live Workspace a command Phase's steps run in."""

    @property
    def workspace_id(self) -> str: ...

    async def run_bounded(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
        working_directory: str | None = None,
        phase_deadline: datetime | None = None,
    ) -> BoundedCommandResult:
        """Run ``command`` to its end; how it ended is a typed terminal (D3)."""
        ...

    async def inject_files(self, files: list[tuple[str, bytes]]) -> None:
        """Write files, paths relative to the workspace root."""
        ...

    async def interrupt(self) -> bool:
        """Stop what is running; True once it is confirmed over."""
        ...
