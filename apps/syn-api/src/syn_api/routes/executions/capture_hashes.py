"""Name the representation behind every hash a capture receipt carries (row 11)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from syn_api.types import CaptureRevisionHashes
from syn_domain.contexts.agent_sessions import CaptureReceipt

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import InventoryItem

_ARCHIVE = re.compile(r"^[a-f0-9]{64}$")
_CONTENT = re.compile(r"^sha256:[a-f0-9]{64}$")


def capture_revision_hashes(items: tuple[InventoryItem, ...]) -> tuple[CaptureRevisionHashes, ...]:
    """Name each capture receipt's hash representations, parallel to ``items``."""
    named: list[CaptureRevisionHashes] = []
    for item in items:
        if not isinstance(item, CaptureReceipt):
            named.append(CaptureRevisionHashes())
            continue
        revision = item.transcript_revision
        archived = item.archived_byte_hash
        content = revision if revision is not None and _CONTENT.fullmatch(revision) else None
        kind: Literal["archived_bytes_sha256", "source_content_hash", "unqualified"] | None
        if revision is None:
            kind = None
        elif item.destination == "local" and revision == archived and _ARCHIVE.fullmatch(revision):
            kind = "archived_bytes_sha256"
        elif item.destination == "remote" and content is not None:
            kind = "source_content_hash"
        else:
            kind = "unqualified"
        named.append(
            CaptureRevisionHashes(
                transcript_revision_kind=kind,
                archived_bytes_sha256=archived,
                source_content_hash=content if kind == "source_content_hash" else None,
            )
        )
    return tuple(named)
