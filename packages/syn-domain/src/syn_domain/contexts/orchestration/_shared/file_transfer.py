"""What a workspace would not give back when its files were read (#1913).

The refusal itself is a value object in `FileRefusalValueObjects`; this module
holds the error a read raises when its result is not whole.
"""

from __future__ import annotations

from syn_domain.contexts.orchestration._shared.FileRefusalValueObjects import (
    INCOMPLETE_WALK,
    FileRefusal,
    FileRefusalReason,
    read_refusals,
)

__all__ = [
    "INCOMPLETE_WALK",
    "FileRefusal",
    "FileRefusalReason",
    "FilesRefusedError",
    "read_refusals",
]


class FilesRefusedError(RuntimeError):
    """A read refused entries it was asked for, so its result is not whole.

    Carries the files that were read and every refusal by path and reason, so
    a caller that decides a refusal is survivable still has both; nothing is
    flattened to text on the way.
    """

    def __init__(
        self,
        files: tuple[tuple[str, bytes], ...],
        refused: tuple[FileRefusal, ...],
    ) -> None:
        self.files = files
        self.refused = refused
        super().__init__("refused to read: " + ", ".join(r.describe() for r in refused))

    @property
    def complete(self) -> bool:
        """False when the walk stopped early, so some matching entries are unknown."""
        return not any(r.reason in INCOMPLETE_WALK for r in self.refused)
