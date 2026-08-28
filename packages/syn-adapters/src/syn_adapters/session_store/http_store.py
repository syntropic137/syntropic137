"""Read one session back out of an APS-V1-0004 conforming store.

THREE BEHAVIOURS HERE ARE THE OPPOSITE OF ADAPTER CONVENTION, and each one is
load-bearing for the caller's retry semantics rather than a style choice.

1. IT RAISES. ``resolve_delegate_usage`` catches ``Exception`` and marks the
   result TRANSIENT - "retry under a bound". An adapter that catches transport
   faults and returns ``None`` instead converts a retryable failure into
   MISSING, which is retired on entirely different terms. Swallowing here is
   how a reset connection becomes a permanently unpriced delegate.

2. ``None`` MEANS GENUINELY ABSENT, and only that. The store answered, and does
   not have this session. Not a timeout, not a 5xx, not a malformed body.

3. IT NEVER STAMPS THE REQUESTED ID ONTO THE RESPONSE. The caller refuses any
   record whose ``session_id`` differs from the one asked for, which is the
   guard against a stale or misrouted response handing back the LEADER's
   transcript under a delegate's attribution. Normalising the id would look
   like defensiveness and would silently disable that guard - the same shape as
   a whitespace-trimming "fix" that removes the discriminator it was protecting.

``source_format`` and ``raw`` come from the record, never inferred. Inferring
the format produced a literal matching no real record; assuming the raw shape
silently unpriced an entire harness. The store serves codex ``raw`` as a LIST
from the detail endpoint and as TEXT from ``/raw``; both are passed through
untouched because ``_as_rollout`` downstream accepts either.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from syn_domain.contexts.agent_sessions.delegate_usage import StoredSession

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.transcript_usage import StoredTranscript

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 20.0


class SessionStoreResponseError(RuntimeError):
    """The store answered, but not with a session this can read.

    Raised rather than returned as ``None`` so the caller classifies it
    TRANSIENT. A body that cannot be parsed today may parse on the next attempt
    (a truncated response, a proxy error page), and treating it as "the store
    does not have this" would retire a retry that might have succeeded.
    """


class HttpSessionStore:
    """``SessionStorePort`` over the store's HTTP API.

    ADR-060: durable-backed and fail-fast. There is no in-memory fallback -
    an unconfigured store is a wiring error the caller must see, not a silent
    degradation into pricing nothing.
    """

    def __init__(
        self,
        base_url: str,
        *,
        auth_token: str | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url or not base_url.strip():
            msg = "session store base_url is required; refusing to construct an unusable store"
            raise ValueError(msg)
        self._base_url = base_url.rstrip("/")
        self._auth_token = auth_token
        self._timeout = timeout_seconds
        self._client = client

    def _headers(self) -> dict[str, str]:
        if not self._auth_token:
            return {}
        return {"Authorization": f"Bearer {self._auth_token}"}

    async def fetch_session(self, session_id: str) -> StoredSession | None:
        """The stored session, or ``None`` if the store does not have it.

        Raises on anything else. See the module docstring for why.
        """
        url = f"{self._base_url}/v1/sessions/{session_id}"
        if self._client is not None:
            response = await self._client.get(url, headers=self._headers(), timeout=self._timeout)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=self._headers())

        if response.status_code == 404:
            # The one absence the store can actually assert.
            return None
        # 5xx, 401, 429 and friends all raise, so the caller retries them
        # rather than recording the delegate as having no transcript.
        response.raise_for_status()

        try:
            payload: Any = response.json()
        except ValueError as exc:
            msg = f"session {session_id!r}: store returned a non-JSON body"
            raise SessionStoreResponseError(msg) from exc

        if not isinstance(payload, dict):
            msg = f"session {session_id!r}: expected a JSON object, got {type(payload).__name__}"
            raise SessionStoreResponseError(msg)

        return _to_stored_session(session_id, payload)


def _to_stored_session(requested_id: str, payload: dict[str, Any]) -> StoredSession:
    """Build a ``StoredSession`` from the record AS THE STORE REPORTED IT.

    ``session_id`` is read from the body and never replaced with
    ``requested_id``. If the store returns the wrong record, the caller's
    equality check is what catches it, and that check only works if this
    faithfully reports what arrived.
    """
    stored_id = payload.get("session_id")
    if not isinstance(stored_id, str) or not stored_id:
        msg = f"session {requested_id!r}: record has no usable session_id"
        raise SessionStoreResponseError(msg)

    source_format = payload.get("source_format")
    if not isinstance(source_format, str) or not source_format:
        # Refused rather than guessed. An inferred format is what matched no
        # real record and left every codex transcript unpriced.
        msg = f"session {requested_id!r}: record has no source_format"
        raise SessionStoreResponseError(msg)

    if "raw" not in payload:
        msg = f"session {requested_id!r}: record has no raw transcript"
        raise SessionStoreResponseError(msg)
    raw: StoredTranscript = payload["raw"]

    metadata = payload.get("metadata")
    model = metadata.get("model") if isinstance(metadata, dict) else None
    if model is not None and not isinstance(model, str):
        model = None

    return StoredSession(
        session_id=stored_id,
        source_format=source_format,
        raw=raw,
        model=model,
    )
