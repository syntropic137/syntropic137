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
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

#: Below this, the credential is close enough that a re-mint should be scheduled.
#: 48h is deliberately generous: re-minting needs a human at a browser, and a
#: warning nobody can act on before it expires is just an alarm.
WARN_THRESHOLD_HOURS: Final = 48.0

_JWT_SEGMENTS: Final = 3


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


def _decode_exp(access_token: str) -> float | None:
    """Read the ``exp`` claim out of a JWT payload. None if it is not one.

    Padding is restored before decoding because JWT segments are base64url with
    padding stripped, which ``urlsafe_b64decode`` rejects.
    """
    if access_token.count(".") != _JWT_SEGMENTS - 1:
        return None
    payload = access_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(claims, dict):
        return None
    exp = claims.get("exp")
    return float(exp) if isinstance(exp, (int, float)) else None


def _unreadable(detail: str) -> CodexAuthStatus:
    return CodexAuthStatus(state=CodexAuthState.UNREADABLE, detail=detail)


def _extract_expiry(raw: str) -> float | CodexAuthStatus:
    """The access token's ``exp``, or the status explaining why there isn't one.

    Split out of ``describe_codex_auth`` so that parsing and classification are
    separately readable: every branch here is a reason the credential cannot be
    dated, and every branch there is a judgement about a date we have.
    """
    try:
        parsed: object = json.loads(raw)
    except ValueError:
        return _unreadable("CODEX_AUTH_JSON is not valid JSON.")
    if not isinstance(parsed, dict):
        return _unreadable("CODEX_AUTH_JSON is not a JSON object.")

    tokens = parsed.get("tokens")
    access_token = tokens.get("access_token") if isinstance(tokens, dict) else None
    exp = _decode_exp(access_token) if isinstance(access_token, str) else None
    if exp is None:
        return _unreadable(
            "Credential present but carries no decodable access-token expiry. "
            "Expected for access-token auth, which does not expire on a timer."
        )
    return exp


def describe_codex_auth(raw: str | None) -> CodexAuthStatus:
    """Describe the credential's freshness from its raw JSON.

    Accepts the raw ``CODEX_AUTH_JSON`` value. Every failure mode resolves to a
    state rather than an exception: this is called from a health endpoint, and a
    freshness probe that can take the endpoint down is worse than no probe.
    """
    if not raw or not raw.strip():
        return CodexAuthStatus(
            state=CodexAuthState.ABSENT,
            detail="No CODEX_AUTH_JSON configured; codex phases cannot authenticate.",
        )

    found = _extract_expiry(raw)
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
