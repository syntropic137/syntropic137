"""Normalized observations of a native transcript, independent of source format."""

from typing import Annotated, Literal

from pydantic import Field

from .session_inventory import Identifier, InventoryModel


class NativeRelationshipFact(InventoryModel):
    parent_native_id: Identifier
    child_native_id: Identifier
    relation: Literal["spawn", "fork", "resume"]
    basis: Literal["parent_call_result", "child_header"]
    mechanism: Identifier
    source_lines: tuple[Annotated[int, Field(ge=1)], ...] = Field(min_length=1, max_length=16)
    call_id: Identifier | None = None


class NativeTranscriptFacts(InventoryModel):
    native_id: Identifier | None
    root_native_id: Identifier | None = None
    identity_lines: tuple[Annotated[int, Field(ge=1)], ...] = Field(default=(), max_length=16)
    relationships: tuple[NativeRelationshipFact, ...] = ()
    issues: tuple[Identifier, ...] = ()
    extractor_version: Identifier
    supported: bool = True
    byte_count: int = Field(ge=0)
