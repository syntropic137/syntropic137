"""Report how long the codex credential has left, without revealing it.

WHY THIS EXISTS. A ChatGPT account has exactly one credential lineage: a second
``codex login`` revokes the first server-side, access token included. So a
deployment and a laptop cannot each hold their own, and the deployment's copy is
periodically re-minted by hand. Verified 2026-08-27.

Between re-mints the arrangement is stable, because a run does NOT refresh while
the access token is valid. What bites is the boundary: the access token expires
(240 hours), a run tries to refresh with a revoked refresh token, and the phase
fails with a message that names no credential at all.

That failure was invisible until it happened. This module makes the remaining
time queryable so a stale credential is a scheduled chore rather than a surprise
outage, which matters more the more instances there are: each one holds its own
copy and can go stale independently.

SECURITY. Only the JWT ``exp`` claim is decoded, and only to compute a duration.
No token material is returned, logged, or rendered. The claims are NOT verified,
because this is a local freshness hint and not an authentication decision;
treating an unverifiable claim as advisory is the point. A caller must never
gate access on this.

API KEYS (#1971). An OpenAI API key, from ``OPENAI_API_KEY`` or an API-key-mode
auth.json, has no token expiry, so it reports its own ``API_KEY`` state instead
of looking ``UNREADABLE``. Only its mode is inspected; the key is never returned.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field

from syn_shared.codex_auth_file import CODEX_AUTH_FILE_FORMAT
from syn_shared.codex_credential_port import CodexCredentialFileKind
from syn_shared.codex_credentials import CodexCredentialSource

if TYPE_CHECKING:
    from syn_shared.codex_credential_port import CodexCredentialFileFormat

#: Below this, the credential is close enough that a re-mint should be scheduled.
#: 48h is deliberately generous: re-minting needs a human at a browser, and a
#: warning nobody can act on before it expires is just an alarm.
WARN_THRESHOLD_HOURS: Final = 48.0


class CodexAuthState(StrEnum):
    """Freshness of the configured codex credential."""

    ABSENT = "absent"
    """No credential configured. Codex phases will fail, by configuration."""

    OK = "ok"
    """Valid with comfortable headroom."""

    EXPIRING = "expiring"
    """Valid, but inside the warning window. Re-mint soon."""

    EXPIRED = "expired"
    """Past expiry. Codex phases are failing now."""

    UNREADABLE = "unreadable"
    """Present but its expiry could not be determined. Not an error on its own:
    an access-token credential carries no JWT to decode."""

    API_KEY = "api_key"
    """An OpenAI API key, from ``OPENAI_API_KEY`` or an API-key-mode
    ``CODEX_AUTH_JSON`` (#1971). It has no token expiry to report, so there is
    nothing to re-mint on a schedule."""


class CodexAuthStatus(BaseModel):
    """A non-secret description of the configured codex credential."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: CodexAuthState
    expires_in_hours: float | None = Field(
        default=None,
        description="Hours until the access token expires. Negative once expired.",
    )
    expires_at: datetime | None = Field(default=None, description="Access token expiry, UTC.")
    detail: str = Field(description="Human-readable summary. Never contains token material.")

    @property
    def needs_attention(self) -> bool:
        """True when someone should act. UNREADABLE is deliberately excluded.

        An access-token credential has no JWT and is legitimately unreadable, so
        treating that as actionable would cry wolf on a perfectly good setup.
        """
        return self.state in (CodexAuthState.EXPIRED, CodexAuthState.EXPIRING)


def _unreadable(detail: str) -> CodexAuthStatus:
    return CodexAuthStatus(state=CodexAuthState.UNREADABLE, detail=detail)


def _api_key_status(source: CodexCredentialSource) -> CodexAuthStatus:
    origin = (
        "OPENAI_API_KEY"
        if source is CodexCredentialSource.OPENAI_API_KEY
        else "an API-key CODEX_AUTH_JSON"
    )
    return CodexAuthStatus(
        state=CodexAuthState.API_KEY,
        detail=(
            f"Codex authenticates with an OpenAI API key from {origin}. "
            "API keys carry no token expiry, so there is nothing to re-mint."
        ),
    )


#: Why a credential file of each non-dated kind cannot be dated. Must cover every
#: kind except API_KEY and TOKENS; ``test_every_undated_kind_has_a_detail``
#: pins that, so a new kind fails a test rather than raising KeyError in /health
#: (where ``describe_codex_auth_health`` would swallow it and drop the block).
_UNDATED_DETAIL: Final[dict[CodexCredentialFileKind, str]] = {
    CodexCredentialFileKind.NOT_JSON: "CODEX_AUTH_JSON is not valid JSON.",
    CodexCredentialFileKind.NOT_AN_OBJECT: "CODEX_AUTH_JSON is not a JSON object.",
    CodexCredentialFileKind.MALFORMED: (
        "CODEX_AUTH_JSON is a JSON object whose fields do not have the types codex expects."
    ),
    CodexCredentialFileKind.API_KEY_WITHOUT_KEY: (
        "CODEX_AUTH_JSON is in API-key mode but carries no usable OPENAI_API_KEY; "
        "codex phases cannot authenticate."
    ),
}


def _extract_expiry(
    raw: str, credential_format: CodexCredentialFileFormat
) -> float | CodexAuthStatus:
    """The access token's ``exp``, or the status explaining why there isn't one.

    Split out of ``describe_codex_auth`` so that parsing and classification are
    separately readable: every branch here is a reason the credential cannot be
    dated, and every branch there is a judgement about a date we have. Reading
    the file is the port's job (``credential_format``); this only maps kinds.
    """
    found = credential_format.classify(raw)
    if found.kind is CodexCredentialFileKind.API_KEY:
        return _api_key_status(CodexCredentialSource.CODEX_AUTH_JSON)
    if found.kind is not CodexCredentialFileKind.TOKENS:
        return _unreadable(_UNDATED_DETAIL[found.kind])
    if found.access_token_expiry is None:
        return _unreadable(
            "Credential present but carries no decodable access-token expiry. "
            "Expected for access-token auth, which does not expire on a timer."
        )
    return found.access_token_expiry


def describe_codex_auth(
    raw: str | None,
    *,
    source: CodexCredentialSource = CodexCredentialSource.CODEX_AUTH_JSON,
    credential_format: CodexCredentialFileFormat = CODEX_AUTH_FILE_FORMAT,
) -> CodexAuthStatus:
    """Describe the credential's freshness from its raw JSON.

    Accepts the auth.json text a codex phase would be given: the raw
    ``CODEX_AUTH_JSON`` value, or the file synthesised from ``OPENAI_API_KEY``
    (pass ``source`` so the detail names the right setting). Every failure mode
    resolves to a state rather than an exception: this is called from a health
    endpoint, and a freshness probe that can take the endpoint down is worse
    than no probe.
    """
    if not raw or not raw.strip():
        return CodexAuthStatus(
            state=CodexAuthState.ABSENT,
            detail=(
                "Neither CODEX_AUTH_JSON nor OPENAI_API_KEY is configured; "
                "codex phases cannot authenticate."
            ),
        )
    if source is CodexCredentialSource.OPENAI_API_KEY:
        return _api_key_status(source)

    found = _extract_expiry(raw, credential_format)
    if isinstance(found, CodexAuthStatus):
        return found

    remaining_hours = (found - time.time()) / 3600
    if remaining_hours <= 0:
        state = CodexAuthState.EXPIRED
        detail = (
            f"Codex credential EXPIRED {abs(remaining_hours):.1f}h ago. "
            "Codex phases are failing now. Re-mint: just codex-reauth"
        )
    elif remaining_hours <= WARN_THRESHOLD_HOURS:
        state = CodexAuthState.EXPIRING
        detail = (
            f"Codex credential expires in {remaining_hours:.1f}h. "
            "Re-mint before then: just codex-reauth"
        )
    else:
        state = CodexAuthState.OK
        detail = f"Codex credential valid for {remaining_hours:.1f}h."

    return CodexAuthStatus(
        state=state,
        expires_in_hours=round(remaining_hours, 2),
        expires_at=datetime.fromtimestamp(found, tz=UTC),
        detail=detail,
    )
