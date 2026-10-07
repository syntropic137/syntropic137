"""Scoped, short-lived platform tokens that let a workspace read the API (ADR-072).

One question is answered here: *may this workspace-ingress request reach this
route?* Callers do not learn how - the token format, how it is stored, how a
scope maps onto routes - only the answer.

The security properties, each enforced in this module and nowhere else:

- A token is random, shown once at issue, and stored only as its SHA-256.
- A token carries exactly one scope. ``READ`` reaches GET/HEAD on the
  read-only resources in ``_READ_RESOURCES``; there is no scope that can start
  an execution, change a workflow, or read settings or secrets.
- A token expires (store TTL AND an explicit ``expires_at`` check) and is
  revoked when its phase ends.
- The token value is never logged; log lines carry the execution id only.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from syn_adapters.in_memory import InMemoryAdapter

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "synpt_"
_REDIS_KEY_PREFIX = "syn:platform-token:"

# First path segment of every route a READ token may GET. The API mounts its
# routers unprefixed (nginx and Envoy strip ``/api/v1``), so these are the
# paths the app itself routes. Anything absent here is denied, including
# routes added later: the allowlist fails closed.
_READ_RESOURCES = frozenset({"executions", "sessions", "artifacts", "evals", "insights", "health"})
_READ_METHODS = frozenset({"GET", "HEAD"})


class PlatformScope(StrEnum):
    """What a platform token may do. Only READ exists (see ADR-072, "Not granted")."""

    READ = "read"


class PlatformTokenGrant(BaseModel):
    """What the store holds for one token. The token itself is never stored."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    scope: PlatformScope
    expires_at: datetime


class PlatformTokenStore(Protocol):
    """Grants keyed by token hash. Implementations must honour ``ttl_seconds``."""

    async def put(self, token_hash: str, grant: PlatformTokenGrant, ttl_seconds: int) -> None: ...

    async def get(self, token_hash: str) -> PlatformTokenGrant | None: ...

    async def delete(self, token_hash: str) -> None: ...


class InMemoryPlatformTokenStore(InMemoryAdapter):
    """Test/offline store (ADR-060). Expiry is enforced by the service, not here."""

    def __init__(self) -> None:
        super().__init__()
        self._grants: dict[str, PlatformTokenGrant] = {}

    async def put(self, token_hash: str, grant: PlatformTokenGrant, ttl_seconds: int) -> None:
        del ttl_seconds
        self._grants[token_hash] = grant

    async def get(self, token_hash: str) -> PlatformTokenGrant | None:
        return self._grants.get(token_hash)

    async def delete(self, token_hash: str) -> None:
        self._grants.pop(token_hash, None)


class RedisPlatformTokenStore:
    """Durable store: one key per token hash, expiring with the token."""

    def __init__(self, redis: AsyncRedis) -> None:
        self._redis = redis

    async def put(self, token_hash: str, grant: PlatformTokenGrant, ttl_seconds: int) -> None:
        await self._redis.set(
            _REDIS_KEY_PREFIX + token_hash, grant.model_dump_json(), ex=ttl_seconds
        )

    async def get(self, token_hash: str) -> PlatformTokenGrant | None:
        raw: bytes | str | None = await self._redis.get(_REDIS_KEY_PREFIX + token_hash)
        return None if raw is None else PlatformTokenGrant.model_validate_json(raw)

    async def delete(self, token_hash: str) -> None:
        await self._redis.delete(_REDIS_KEY_PREFIX + token_hash)


@dataclass(frozen=True)
class Denial:
    """Why a workspace-ingress request was refused. ``status`` is 401 or 403."""

    status: int
    reason: str


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _scope_allows(scope: PlatformScope, method: str, path: str) -> bool:
    if scope is not PlatformScope.READ or method.upper() not in _READ_METHODS:
        return False
    first = path.lstrip("/").split("/", 1)[0]
    return first in _READ_RESOURCES


@dataclass(frozen=True)
class WorkspacePlatformGrant:
    """One phase's access to the API: what its agent is given, and what teardown revokes."""

    api_url: str
    token: str = field(repr=False)

    @property
    def env(self) -> dict[str, str]:
        """The variables the ``syn`` CLI already reads (``apps/syn-cli-node/src/config.ts``)."""
        return {"SYN_API_URL": self.api_url, "SYN_API_TOKEN": self.token}


class PlatformTokenService:
    """Issues, revokes and checks platform tokens.

    ``store=None`` IS the disabled state: nothing can be issued and every
    workspace-ingress request is refused, so "off" cannot be half-wired.
    """

    def __init__(
        self,
        store: PlatformTokenStore | None,
        *,
        max_ttl_seconds: int,
        workspace_api_url: str = "http://envoy-proxy:8081/syn-platform",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._max_ttl = max_ttl_seconds
        self._api_url = workspace_api_url
        self._now = now or (lambda: datetime.now(UTC))

    @property
    def enabled(self) -> bool:
        return self._store is not None

    async def issue(self, execution_id: str, scope: PlatformScope = PlatformScope.READ) -> str:
        """Mint a token for one execution's phase. Raises if access is disabled."""
        if self._store is None:
            msg = "platform access is disabled (SYN_PLATFORM_ACCESS_ENABLED=false)"
            raise PermissionError(msg)
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        grant = PlatformTokenGrant(
            execution_id=execution_id,
            scope=scope,
            expires_at=self._now() + timedelta(seconds=self._max_ttl),
        )
        await self._store.put(_hash(token), grant, self._max_ttl)
        logger.info("Issued %s platform token for execution %s", scope, execution_id)
        return token

    async def grant_workspace(self, execution_id: str) -> WorkspacePlatformGrant | None:
        """A read-only grant for one workspace, or ``None`` while access is OFF."""
        if self._store is None:
            return None
        return WorkspacePlatformGrant(self._api_url, await self.issue(execution_id))

    async def revoke(self, token: str) -> None:
        """Make ``token`` unusable immediately. Idempotent."""
        if self._store is not None:
            await self._store.delete(_hash(token))

    async def authorize(self, authorization: str | None, method: str, path: str) -> Denial | None:
        """``None`` if the request may proceed, otherwise why it may not."""
        if self._store is None:
            return Denial(403, "workspace platform access is disabled")
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token.startswith(TOKEN_PREFIX):
            return Denial(401, "platform token required")
        grant = await self._store.get(_hash(token))
        if grant is None or grant.expires_at <= self._now():
            return Denial(401, "platform token invalid, expired or revoked")
        if not _scope_allows(grant.scope, method, path):
            return Denial(
                403, f"platform token scope '{grant.scope}' does not allow {method} {path}"
            )
        return None


__all__ = [
    "TOKEN_PREFIX",
    "Denial",
    "InMemoryPlatformTokenStore",
    "PlatformScope",
    "PlatformTokenGrant",
    "PlatformTokenService",
    "PlatformTokenStore",
    "RedisPlatformTokenStore",
    "WorkspacePlatformGrant",
]
