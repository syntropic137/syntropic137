"""Tell a webhook that an execution ended, signed so the receiver can trust it (#1661).

One POST per ``deliver``. The body is the notice as JSON; two headers carry
what the receiver needs and the body does not:

- ``Idempotency-Key: <execution_id>:<outcome>``, the notice's ``key`` in the
  same string form the to-do list stores it under. The port promises one
  delivery per key, and the process manager re-offers an owed notice after a
  crash, so the receiver drops a key it has already seen.
- ``X-Syn-Signature-256: sha256=<hex>``, an HMAC-SHA256 of the exact body bytes
  keyed by the shared secret. The bytes signed are the bytes sent: the body is
  serialised once and never re-encoded by the client.

There is no retry loop. Any answer but a 2xx, a timeout or a transport error
raises ``LifecycleNoticeUndeliveredError``; the notice then stays owed and the
process manager's next pass is the retry. Neither the secret nor the signature
is ever logged or put in an error message.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import TYPE_CHECKING

import httpx

from syn_domain.contexts.orchestration.slices.notify_execution_lifecycle.value_objects import (
    LifecycleNoticeRecord,
)

if TYPE_CHECKING:
    from pydantic import SecretStr

    from syn_domain.contexts.orchestration.slices.notify_execution_lifecycle.value_objects import (
        ExecutionLifecycleNotice,
    )

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
SIGNATURE_HEADER = "X-Syn-Signature-256"

_DEFAULT_TIMEOUT_SECONDS = 10.0


class LifecycleNoticeUndeliveredError(RuntimeError):
    """The webhook did not acknowledge the notice, so it is still owed."""


def sign(secret: SecretStr, body: bytes) -> str:
    """The signature header value for ``body``: ``sha256=`` and the hex HMAC."""
    digest = hmac.new(secret.get_secret_value().encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class WebhookExecutionLifecycleSink:
    """``ExecutionLifecycleSinkPort`` over a signed HTTP POST to one URL."""

    def __init__(
        self,
        url: str,
        secret: SecretStr,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not url.strip():
            raise ValueError("lifecycle webhook url is required")
        if not secret.get_secret_value():
            raise ValueError(
                "lifecycle webhook secret is required; an unsigned notice is forgeable"
            )
        self._url = url
        self._secret = secret
        self._client = client
        self._timeout = timeout_seconds

    async def deliver(self, notice: ExecutionLifecycleNotice) -> None:
        body = json.dumps(notice.model_dump(mode="json")).encode()
        # The record's key, not a second spelling of it: receiver and store dedup alike.
        key = LifecycleNoticeRecord(notice=notice).key
        headers = {
            "Content-Type": "application/json",
            IDEMPOTENCY_KEY_HEADER: key,
            SIGNATURE_HEADER: sign(self._secret, body),
        }
        try:
            if self._client is not None:
                response = await self._client.post(
                    self._url, content=body, headers=headers, timeout=self._timeout
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(self._url, content=body, headers=headers)
        # RequestError covers timeouts, refused connections and undecodable replies.
        except httpx.RequestError as exc:
            raise LifecycleNoticeUndeliveredError(
                f"lifecycle notice {key} was not delivered to the webhook at "
                f"{httpx.URL(self._url).host}: {type(exc).__name__}; it stays owed"
            ) from exc
        if not response.is_success:
            raise LifecycleNoticeUndeliveredError(
                f"lifecycle notice {key} was refused by the webhook at "
                f"{httpx.URL(self._url).host} with HTTP {response.status_code}; it stays owed"
            )
