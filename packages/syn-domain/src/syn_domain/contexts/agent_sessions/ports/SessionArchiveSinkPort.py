"""Ask the remote session archive whether it holds one exact uploaded revision.

A local transcript body may only leave disk when the archive it was uploaded to
confirms the same revision (#2107). This port asks that question and keeps the
store's answers distinct: an archive that is down, refuses credentials or holds
a corrupt body is never "absent", and none of them is "confirmed".

The question is about the revision this installation UPLOADED: its qualified
identity and the original-content hash persisted before the upload. It is never
recomputed from a later local revision or from a stored form.

Confirmation is not backup evidence. A confirmed revision is durably committed
in the archive, which may still supersede it later; whether that archive is
itself backed up off-site is a separate fact the caller must hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Protocol

from pydantic import Field

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import InventoryModel

_SHA256 = r"^sha256:[a-f0-9]{64}$"


class UploadedRevision(InventoryModel):
    """One revision as uploaded: qualified transcript identity plus content hash."""

    source_instance_id: Annotated[str, Field(min_length=1, max_length=128)]
    harness: Annotated[str, Field(min_length=1)]
    native_session_id: Annotated[str, Field(min_length=1)]
    content_hash: Annotated[str, Field(pattern=_SHA256)]


@dataclass(frozen=True, slots=True)
class RevisionConfirmed:
    """The archive committed this exact revision durably."""

    stored_content_hash: str
    body_verified: bool
    """The archive re-verified body integrity, not only committed metadata."""


@dataclass(frozen=True, slots=True)
class RevisionAbsent:
    """The archive does not hold this revision, including a superseded one."""


@dataclass(frozen=True, slots=True)
class ConfirmUnauthorized:
    status: int


@dataclass(frozen=True, slots=True)
class RevisionIntegrityFailure:
    """The archive holds the revision but its body failed verification."""


@dataclass(frozen=True, slots=True)
class ArchiveUnavailable:
    """The archive could not answer: 503, timeout, or connection failure."""


@dataclass(frozen=True, slots=True)
class ConfirmNotAdvertised:
    """The archive does not advertise revision confirmation at all."""


@dataclass(frozen=True, slots=True)
class ConfirmUnexpectedResponse:
    """An answer outside the contract. Never read as absent or confirmed."""

    status: int


type RevisionConfirmation = (
    RevisionConfirmed
    | RevisionAbsent
    | ConfirmUnauthorized
    | RevisionIntegrityFailure
    | ArchiveUnavailable
    | ConfirmNotAdvertised
    | ConfirmUnexpectedResponse
)


class SessionArchiveSinkPort(Protocol):
    async def confirm(self, revision: UploadedRevision) -> RevisionConfirmation:
        """Ask now; callers confirm immediately before acting on the answer.

        Never raises for a store answer or a transport failure: every outcome
        is one variant of the union, so no caller can fold one into another
        by catching an exception.
        """
        ...
