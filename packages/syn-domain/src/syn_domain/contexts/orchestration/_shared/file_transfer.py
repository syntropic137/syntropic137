"""What a workspace would not give back when its files were read (#1913).

A workspace is untrusted, so the provider's read refuses some entries rather
than return them: a link, a special file, one past a read limit. Each refusal
names the path and the reason, and is never turned into a missing file or an
empty one. The reasons are the provider contract's own; the adapter hands its
refusals across unchanged, so a reason added there and not here fails pyright
at that hand-over instead of arriving as an unknown string.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

FileRefusalReason = Literal[
    "hard_link",
    "symlink",
    "escaping_symlink",
    "special_file",
    "vanished",
    "file_too_large",
    "total_bytes_exceeded",
    "depth_exceeded",
    "entry_limit_exceeded",
]

#: Refusals after which nobody knows what the files asked for were: the walk
#: stopped, so entries past it were neither read nor refused.
INCOMPLETE_WALK: frozenset[FileRefusalReason] = frozenset(
    {"entry_limit_exceeded", "depth_exceeded"}
)


class FileRefusal(BaseModel):
    """One entry a read would not return, relative to its root, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    reason: FileRefusalReason

    def describe(self) -> str:
        return f"{self.path} ({self.reason})"


def read_refusals(raw: object) -> tuple[FileRefusal, ...]:
    """The refusals on a replayed event, typed whether stored as models or as dicts."""
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(r if isinstance(r, FileRefusal) else FileRefusal.model_validate(r) for r in raw)


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
