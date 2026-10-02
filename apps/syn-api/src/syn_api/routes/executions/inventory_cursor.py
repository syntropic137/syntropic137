"""Opaque inventory continuation cursors (#1398 row 8).

A cursor binds the run scope, the pinned revision, the section, the membership
filters and the keyset ordering key. It is not an access credential: every page
still re-checks run visibility. Clients must treat it as opaque.
"""

from __future__ import annotations

import base64
import binascii
from typing import Literal
from uuid import UUID  # noqa: TC003 - Pydantic resolves this field at runtime

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from syn_domain.contexts.agent_sessions import (  # noqa: TC001 - runtime Pydantic fields
    InventoryFilter,
    ItemKind,
    RunIdentity,
)

MismatchField = Literal["scope", "revision", "section", "filters"]
MAX_CURSOR_LENGTH = 8192


class InventoryCursorInvalid(ValueError):
    """The token is not a cursor this server issued."""


class _CursorBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    v: Literal[1]
    run: RunIdentity
    snapshot_id: UUID
    kind: ItemKind
    filters: InventoryFilter
    after: int = Field(ge=0)


class InventoryCursor(_CursorBody):
    def encode(self) -> str:
        return base64.urlsafe_b64encode(self.model_dump_json().encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, token: str) -> InventoryCursor:
        if not token or len(token) > MAX_CURSOR_LENGTH:
            raise InventoryCursorInvalid("cursor is empty or too long")
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            return cls.model_validate_json(raw)
        except (binascii.Error, ValueError, ValidationError) as exc:
            raise InventoryCursorInvalid("cursor is malformed") from exc

    def mismatches(
        self, run: RunIdentity, snapshot_id: UUID, kind: ItemKind, filters: InventoryFilter
    ) -> tuple[MismatchField, ...]:
        found: list[MismatchField] = []
        if self.run != run:
            found.append("scope")
        if self.snapshot_id != snapshot_id:
            found.append("revision")
        if self.kind != kind:
            found.append("section")
        if self.filters != filters:
            found.append("filters")
        return tuple(found)


def issue_cursor(
    run: RunIdentity, snapshot_id: UUID, kind: ItemKind, filters: InventoryFilter, after: int
) -> str:
    return InventoryCursor(
        v=1, run=run, snapshot_id=snapshot_id, kind=kind, filters=filters, after=after
    ).encode()
