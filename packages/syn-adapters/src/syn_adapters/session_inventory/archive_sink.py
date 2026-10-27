"""``SessionArchiveSinkPort`` through the standard exporter, never a second HTTP client.

The exporter is the only process that talks to the session store. This module
holds the whole ``--capture-confirm`` CLI contract syn137 depends on: argument,
stdin document, stdout document and exit codes. It is defined in
AgentParadise/agentic-session-exporter PR #31 (docs/qualified-capture.md,
"Revision confirmation"), which implements the DRAFT APS-V1-0004 revision
confirmation in AgentParadise/agent-paradise-standards-system PR #154. HTTP
paths, headers and capability keys live in the exporter, so a ruling on the
draft does not touch this file unless the CLI contract itself changes.

Every outcome stays distinct. A failure to run the exporter, a non-zero exit
or an output outside the contract is never "absent" and never "confirmed":
the exporter could not answer, so the archive is reported ``ArchiveUnavailable``
(exporter process failure) or ``ConfirmUnexpectedResponse`` (contract breach).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from syn_domain.contexts.agent_sessions.ports.SessionArchiveSinkPort import (
    ArchiveUnavailable,
    ConfirmNotAdvertised,
    ConfirmUnauthorized,
    ConfirmUnexpectedResponse,
    RevisionAbsent,
    RevisionConfirmation,
    RevisionConfirmed,
    RevisionIntegrityFailure,
)

from .exporter_transport import ExporterTransportError, capture_confirm

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.ports.SessionArchiveSinkPort import UploadedRevision

    from .exporter_transport import ExporterConfirmConfig

logger = logging.getLogger(__name__)

# --- Exporter CLI contract (agentic-session-exporter PR #31). ---------------
CONFIRM_ARGUMENTS: Final = ("--capture-confirm",)
EXIT_OUTCOME: Final = 0
"""Exit 0: stdout carries exactly one outcome document, whatever the outcome."""
# Any other exit (1 configuration or input, 2 usage) prints no document.
# -----------------------------------------------------------------------------

_SHA256 = r"^sha256:[a-f0-9]{64}$"


class _Identity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_instance_id: str
    harness: str
    native_session_id: str


class _ConfirmRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    identity: _Identity
    content_hash: str = Field(pattern=_SHA256)


class _ConfirmDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    schema_version: Literal[1]
    outcome: Literal[
        "confirmed",
        "absent",
        "unauthorized",
        "integrity_failure",
        "unavailable",
        "not_advertised",
        "unexpected",
    ]
    status: int | None
    stored_content_hash: str | None = Field(pattern=_SHA256)
    body_verified: bool | None


def _outcome(document: _ConfirmDocument) -> RevisionConfirmation:
    status = document.status or 0
    match document.outcome:
        case "confirmed":
            if document.stored_content_hash is None or document.body_verified is None:
                return ConfirmUnexpectedResponse(status=status)
            return RevisionConfirmed(
                stored_content_hash=document.stored_content_hash,
                body_verified=document.body_verified,
            )
        case "absent":
            return RevisionAbsent()
        case "unauthorized":
            return ConfirmUnauthorized(status=status)
        case "integrity_failure":
            return RevisionIntegrityFailure()
        case "unavailable":
            return ArchiveUnavailable()
        case "not_advertised":
            return ConfirmNotAdvertised()
        case "unexpected":
            return ConfirmUnexpectedResponse(status=status)


class ExporterArchiveSink:
    """Read-scoped revision confirmation by running the standard exporter."""

    def __init__(self, config: ExporterConfirmConfig) -> None:
        self._config = config

    async def confirm(self, revision: UploadedRevision) -> RevisionConfirmation:
        request = _ConfirmRequest(
            identity=_Identity(
                source_instance_id=revision.source_instance_id,
                harness=revision.harness,
                native_session_id=revision.native_session_id,
            ),
            content_hash=revision.content_hash,
        )
        try:
            code, output = await capture_confirm(
                self._config, CONFIRM_ARGUMENTS, request.model_dump_json().encode()
            )
        except ExporterTransportError:
            logger.warning("Archive confirmation could not run the exporter")
            return ArchiveUnavailable()
        if code != EXIT_OUTCOME:
            # Exit codes only; exporter output can name the store.
            logger.warning("Archive confirmation exporter exited %d", code)
            return ArchiveUnavailable()
        try:
            document = _ConfirmDocument.model_validate_json(output)
        except ValidationError:
            return ConfirmUnexpectedResponse(status=0)
        return _outcome(document)
