"""Scoped, short-lived platform tokens that let a workspace read the API (ADR-072).

One question is answered here: *may this workspace-ingress request reach this
route?* Callers do not learn how - the token format, how it is stored, how a
scope maps onto routes - only the answer.

The security properties, each enforced in this module and nowhere else:

- A token is random, shown once at issue, and stored only as its SHA-256.
- A token carries exactly one scope. ``READ`` reaches GET/HEAD on the
  read-only resources in ``_READ_RESOURCES``. ``EVAL`` (#1744) reaches what
  READ does plus exactly two writes: ``POST /workflows/{id}/execute`` whose
  body names an ``eval_id`` explicitly, and
  ``POST /evals/{id}/runs/{execution}/score``. Both must name the eval the
  issuing execution belongs to (``PlatformTokenGrant.eval_id``); an EVAL grant
  bound to no eval reaches neither. No scope can change a workflow, launch a
  run outside its own eval, or read settings or secrets.
- A token expires (store TTL AND an explicit ``expires_at`` check) and is
  revoked when its phase ends.
- The token value is never logged; log lines carry the execution id only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from syn_adapters.in_memory import InMemoryAdapter
from syn_shared.platform_access import PlatformScope

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

# The largest execute body an EVAL token's request is read up to. A real one is
# a few hundred bytes; anything past this is refused rather than buffered.
MAX_EVAL_BODY_BYTES = 64 * 1024


class PlatformTokenGrant(BaseModel):
    """What the store holds for one token. The token itself is never stored."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    scope: PlatformScope
    expires_at: datetime
    # The eval the issuing execution belongs to: the only eval an EVAL token
    # may launch into or score (#1744). None for READ, and for an EVAL phase
    # whose execution is in no eval, which therefore can write nothing.
    eval_id: str | None = None


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


async def _scope_allows(
    grant: PlatformTokenGrant,
    method: str,
    path: str,
    read_body: Callable[[], Awaitable[bytes]],
) -> bool:
    # Envoy does not normalize paths by default, so a dot or empty segment
    # could name one resource here and route to another downstream.
    segments = path.removeprefix("/").removesuffix("/").split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return False
    method = method.upper()
    if method in _READ_METHODS:
        return segments[0] in _READ_RESOURCES
    own_eval = grant.eval_id
    if grant.scope is not PlatformScope.EVAL or method != "POST" or not own_eval:
        return False
    match segments:
        case ["evals", eval_id, "runs", _, "score"]:
            # Which runs belong to `eval_id` is the scoring route's check.
            return eval_id == own_eval
        case ["workflows", _, "execute"]:
            return _names_eval(await read_body(), own_eval)
        case _:
            return False


def _names_eval(body: bytes, own_eval: str) -> bool:
    """Whether an execute body launches into ``own_eval``, naming it itself.

    Explicit, not merely "not opted out": with no ``eval_id`` the route falls
    back to the workflow's ``default_eval_id``, and a workflow with none runs
    as an ordinary execution - which an EVAL token must not be able to start.
    Parsed the way the route parses it (``json.loads``, last duplicate key
    wins), so this and the route cannot read two different requests.
    """
    if len(body) > MAX_EVAL_BODY_BYTES:
        return False
    try:
        named = _EvalNamedInBody.model_validate(json.loads(body))
    except ValueError:  # json.JSONDecodeError and pydantic.ValidationError both
        return False
    return named.eval_id == own_eval and not named.no_eval


class _EvalNamedInBody(BaseModel):
    """The two execute-body fields that decide an EVAL token's request.

    Typed as ``ExecuteWorkflowRequest`` types them and validated in the same
    lax mode, so ``"no_eval": "true"`` is an opt-out here exactly as it is
    there. Every other field is the route's business.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    eval_id: str | None = None
    no_eval: bool = False


async def _no_body() -> bytes:
    return b""


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

    @property
    def workspace_api_base_path(self) -> str:
        """The path a workspace puts before a router path: ``/syn-platform/api/v1``.

        The CLI appends ``/api/v1`` to ``SYN_API_URL`` (``client/typed.ts``).
        """
        return urlsplit(self._api_url).path.rstrip("/") + "/api/v1"

    async def issue(
        self,
        execution_id: str,
        scope: PlatformScope = PlatformScope.READ,
        eval_id: str | None = None,
    ) -> str:
        """Mint a token for one execution's phase. Raises if access is disabled.

        ``eval_id`` is the eval ``execution_id`` belongs to, and the only one
        an EVAL token may write to.
        """
        if self._store is None:
            msg = "platform access is disabled (SYN_PLATFORM_ACCESS_ENABLED=false)"
            raise PermissionError(msg)
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        grant = PlatformTokenGrant(
            execution_id=execution_id,
            scope=scope,
            expires_at=self._now() + timedelta(seconds=self._max_ttl),
            eval_id=eval_id,
        )
        await self._store.put(_hash(token), grant, self._max_ttl)
        logger.info("Issued %s platform token for execution %s", scope, execution_id)
        return token

    async def grant_workspace(
        self,
        execution_id: str,
        scope: PlatformScope = PlatformScope.READ,
        eval_id: str | None = None,
    ) -> WorkspacePlatformGrant | None:
        """A grant of ``scope`` for one workspace, or ``None`` while access is OFF.

        ``scope`` is what the phase declared (``platform_access``); a phase
        that declared nothing is READ. ``eval_id`` is the eval the execution
        belongs to, read from its aggregate.
        """
        if self._store is None:
            return None
        token = await self.issue(execution_id, scope, eval_id)
        return WorkspacePlatformGrant(self._api_url, token)

    async def bound_to_deadline(self, token: str, deadline: datetime) -> None:
        """Make ``token`` expire no later than ``deadline``. Never extends it.

        The phase deadline is known at launch, after the workspace (and its
        grant) exists. Bounding here means a token whose teardown revocation
        fails still dies with its phase, and a retry carrying the same shared
        deadline changes nothing.
        """
        if self._store is None:
            return
        token_hash = _hash(token)
        grant = await self._store.get(token_hash)
        if grant is None or grant.expires_at <= deadline:
            return
        remaining = (deadline - self._now()).total_seconds()
        if remaining <= 0:
            await self._store.delete(token_hash)
            return
        bounded = grant.model_copy(update={"expires_at": deadline})
        await self._store.put(token_hash, bounded, math.ceil(remaining))

    async def revoke(self, token: str) -> None:
        """Make ``token`` unusable immediately. Idempotent."""
        if self._store is not None:
            await self._store.delete(_hash(token))

    async def authorize(
        self,
        authorization: str | None,
        method: str,
        path: str,
        read_body: Callable[[], Awaitable[bytes]] = _no_body,
    ) -> Denial | None:
        """``None`` if the request may proceed, otherwise why it may not.

        ``read_body`` is called only when the answer depends on the body (an
        EVAL token's execute request), and must return at most
        ``MAX_EVAL_BODY_BYTES`` + 1 bytes; a longer body is refused.
        """
        if self._store is None:
            return Denial(403, "workspace platform access is disabled")
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token.startswith(TOKEN_PREFIX):
            return Denial(401, "platform token required")
        grant = await self._store.get(_hash(token))
        if grant is None or grant.expires_at <= self._now():
            return Denial(401, "platform token invalid, expired or revoked")
        if not await _scope_allows(grant, method, path, read_body):
            return Denial(
                403, f"platform token scope '{grant.scope}' does not allow {method} {path}"
            )
        return None


__all__ = [
    "MAX_EVAL_BODY_BYTES",
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
