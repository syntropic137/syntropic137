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


RevisionKind = Literal["archived_bytes_sha256", "source_content_hash", "unqualified"]


def _revision_kind(item: CaptureReceipt) -> RevisionKind | None:
    """Local receipts store archived byte hashes; replica receipts APSS content hashes."""
    revision = item.transcript_revision
    if revision is None:
        return None
    if (
        item.destination == "local"
        and revision == item.archived_byte_hash
        and _ARCHIVE.fullmatch(revision)
    ):
        return "archived_bytes_sha256"
    if item.destination == "remote" and _CONTENT.fullmatch(revision):
        return "source_content_hash"
    return "unqualified"


def _named(item: InventoryItem) -> CaptureRevisionHashes:
    if not isinstance(item, CaptureReceipt):
        return CaptureRevisionHashes()
    kind = _revision_kind(item)
    return CaptureRevisionHashes(
        transcript_revision_kind=kind,
        archived_bytes_sha256=item.archived_byte_hash,
        source_content_hash=item.transcript_revision if kind == "source_content_hash" else None,
    )


def capture_revision_hashes(items: tuple[InventoryItem, ...]) -> tuple[CaptureRevisionHashes, ...]:
    """Name each capture receipt's hash representations, parallel to ``items``."""
    return tuple(_named(item) for item in items)
