"""``SessionArchiveSinkPort`` over SeshMagic's HTTP API: revision confirmation.

DRAFT CONTRACT. Every wire detail of revision confirmation lives in this one
module: paths, query parameter names, header names and capability keys. They
follow the unratified APSS draft in AgentParadise/agent-paradise-standards-system
PR #154 (APS-V1-0004 base 5.1.1 and 5.3.1, inventory profile "HEAD
/v1/transcripts"). Open owner questions there are the spec version and the
route shape (path or query form). When the draft is ruled, this file is the
only one that changes.

Route choice: Syntropic137 uploads through the qualified capture endpoint
``POST /v1/transcripts`` (the standard exporter's ``--capture-enqueue``), never
through ``POST /v1/sessions/batch``. The draft says qualified uploads are
confirmed through the qualified ``HEAD /v1/transcripts`` form, not the base
``/v1/sessions/{session_id}/revisions/{content_hash}`` route, so that is the one
used here.

Every store answer maps to exactly one outcome and none is folded into another
(base 5.3.1: "MUST NOT fold any of them into absent"). Transport failures are
``ArchiveUnavailable``. Anything the draft does not define, including a 200
without a well-formed stored hash and any redirect, is
``ConfirmUnexpectedResponse``.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Final

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from syn_domain.contexts.agent_sessions.ports.SessionArchiveSinkPort import (
    ArchiveUnavailable,
    ConfirmNotAdvertised,
    ConfirmUnauthorized,
    ConfirmUnexpectedResponse,
    RevisionAbsent,
    RevisionConfirmation,
    RevisionConfirmed,
    RevisionIntegrityFailure,
    UploadedRevision,
)

if TYPE_CHECKING:
    from pydantic import SecretStr

logger = logging.getLogger(__name__)

# --- Draft wire contract (APSS PR #154). Change here, and only here. ---------
CAPABILITIES_PATH: Final = "/v1/capabilities"
CONFIRM_PATH: Final = "/v1/transcripts"
CONFIRM_QUERY_SOURCE: Final = "source_instance_id"
CONFIRM_QUERY_HARNESS: Final = "harness"
CONFIRM_QUERY_NATIVE_ID: Final = "native_session_id"
CONFIRM_QUERY_CONTENT_HASH: Final = "content_hash"
STORED_HASH_HEADER: Final = "X-Stored-Content-Hash"
# Capability keys: "revision_confirm" and "confirm_verifies_body" are the field
# names of ``_Capabilities`` below.
# -----------------------------------------------------------------------------

_STORED_HASH = re.compile(r"sha256:[a-f0-9]{64}")
_DEFAULT_TIMEOUT_SECONDS = 10.0


class _Capabilities(BaseModel):
    # A capability document grows additively (APS-V1-0004 8.3, consumer
    # tolerance): unknown keys such as "request_encodings" are ignored rather
    # than rejected, which is why this boundary model is not extra="forbid".
    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)
    revision_confirm: bool = False
    confirm_verifies_body: bool | None = None


class SeshMagicArchiveSink:
    """Read-scoped revision confirmation. No in-memory state, no fallback."""

    def __init__(
        self,
        base_url: str,
        read_token: SecretStr,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("archive sink base_url is required")
        if not read_token.get_secret_value().strip():
            raise ValueError("archive sink requires a read-scoped token")
        if timeout_seconds <= 0:
            raise ValueError("archive sink timeout must be positive")
        self._base_url = base_url.rstrip("/")
        self._token = read_token
        self._timeout = timeout_seconds
        self._client = client

    async def confirm(self, revision: UploadedRevision) -> RevisionConfirmation:
        try:
            return await self._confirm(revision)
        except httpx.HTTPError as exc:
            # Type only: messages can carry the URL, and the URL carries identity.
            logger.warning("Archive confirmation transport failed (%s)", type(exc).__name__)
            return ArchiveUnavailable()

    async def _confirm(self, revision: UploadedRevision) -> RevisionConfirmation:
        verifies_body = await self._discover()
        if not isinstance(verifies_body, bool):
            return verifies_body
        response = await self._request(
            "HEAD",
            CONFIRM_PATH,
            {
                CONFIRM_QUERY_SOURCE: revision.source_instance_id,
                CONFIRM_QUERY_HARNESS: revision.harness,
                CONFIRM_QUERY_NATIVE_ID: revision.native_session_id,
                CONFIRM_QUERY_CONTENT_HASH: revision.content_hash,
            },
        )
        match response.status_code:
            case 200:
                stored = response.headers.get(STORED_HASH_HEADER)
                if stored is None or _STORED_HASH.fullmatch(stored) is None:
                    return ConfirmUnexpectedResponse(status=200)
                return RevisionConfirmed(stored_content_hash=stored, body_verified=verifies_body)
            case 404:
                return RevisionAbsent()
            case 409:
                return RevisionIntegrityFailure()
            case status:
                return _non_success(status)

    async def _discover(self) -> bool | RevisionConfirmation:
        """``confirm_verifies_body`` when confirmation is advertised, else the outcome."""
        response = await self._request("GET", CAPABILITIES_PATH, None)
        match response.status_code:
            case 200:
                pass
            case 404:
                # No capability document: nothing optional is advertised.
                return ConfirmNotAdvertised()
            case status:
                return _non_success(status)
        try:
            advertised = _Capabilities.model_validate_json(response.content)
        except ValidationError:
            return ConfirmUnexpectedResponse(status=200)
        if not advertised.revision_confirm:
            return ConfirmNotAdvertised()
        if advertised.confirm_verifies_body is None:
            # The draft requires both keys together.
            return ConfirmUnexpectedResponse(status=200)
        return advertised.confirm_verifies_body

    async def _request(
        self, method: str, path: str, params: dict[str, str] | None
    ) -> httpx.Response:
        url = self._base_url + path
        headers = {"Authorization": f"Bearer {self._token.get_secret_value()}"}
        if self._client is not None:
            return await self._client.request(
                method,
                url,
                params=params,
                headers=headers,
                timeout=self._timeout,
                follow_redirects=False,
            )
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
            return await client.request(method, url, params=params, headers=headers)


def _non_success(status: int) -> RevisionConfirmation:
    if status in (401, 403):
        return ConfirmUnauthorized(status=status)
    if status == 503:
        return ArchiveUnavailable()
    return ConfirmUnexpectedResponse(status=status)
