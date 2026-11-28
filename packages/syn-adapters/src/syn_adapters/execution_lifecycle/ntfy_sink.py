"""Tell an ntfy topic that an execution ended, as a phone notification (#1661).

One POST per ``deliver`` to the topic URL, ntfy's publish API
(https://docs.ntfy.sh/publish/). The body is one plain-text line built from the
notice's own fields, e.g. ``exec-4711 failed (wf-9): platform``. Three headers
shape the notification: ``Title``, ``Tags`` (an emoji per outcome) and
``Priority``, raised for a failure so it is the one that buzzes.

ntfy cannot dedupe. It has no idempotency header: a second publish is always a
second stored message. The nearest it offers is a sequence ID
(https://docs.ntfy.sh/publish/#updating-deleting-notifications): a publish
carrying the ID of an earlier one makes clients *replace* that notification
instead of adding another. So the port's "reaches the outside world once" holds
on the clients that honour sequence IDs (ntfy lists Android and Firefox) and
not on the rest, which may show a retry after a crash twice. That is the
weaker half of the contract, and it is accepted for this sink: a duplicate
phone notice is noise, a lost one is the failure nobody hears about.

The server only accepts sequence IDs matching ``[-_A-Za-z0-9]{1,64}``
(``sequenceIDRegex`` in ntfy's ``server/server.go``), which the record's key,
``exec-…:completed``, does not. The ID sent is therefore the SHA-256 hex of
that key: the same key always gives the same ID, and every key gives a valid one.

There is no retry loop, and redirects are never followed, as for the webhook
sink: any answer but a 2xx, a timeout or a transport error raises
``LifecycleNoticeUndeliveredError``, and the process manager's next pass is
the retry. The optional access token is sent as ``Authorization: Bearer`` and
is never logged or put in an error message.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, NamedTuple

import httpx

from syn_adapters.execution_lifecycle.webhook_sink import LifecycleNoticeUndeliveredError
from syn_domain.contexts.orchestration.slices.notify_execution_lifecycle.value_objects import (
    ExecutionOutcome,
    LifecycleNoticeRecord,
)

if TYPE_CHECKING:
    from pydantic import SecretStr

    from syn_domain.contexts.orchestration.slices.notify_execution_lifecycle.value_objects import (
        ExecutionLifecycleNotice,
    )

SEQUENCE_ID_HEADER = "X-Sequence-ID"

_DEFAULT_TIMEOUT_SECONDS = 10.0


class _Look(NamedTuple):
    """How one outcome shows on the phone: ntfy tags and priority (1-5, 3 is default)."""

    tags: str
    priority: int


_LOOKS: dict[ExecutionOutcome, _Look] = {
    ExecutionOutcome.COMPLETED: _Look(tags="white_check_mark", priority=3),
    ExecutionOutcome.FAILED: _Look(tags="x", priority=4),
    ExecutionOutcome.CANCELLED: _Look(tags="no_entry_sign", priority=3),
}


def _message(notice: ExecutionLifecycleNotice) -> str:
    """The one line a person reads: what ended, how, and why when the notice says."""
    line = f"{notice.execution_id} {notice.outcome} ({notice.workflow_id})"
    why = notice.failure_classification or notice.cancel_reason
    return f"{line}: {why}" if why else line


class NtfyExecutionLifecycleSink:
    """``ExecutionLifecycleSinkPort`` over a publish to one ntfy topic."""

    def __init__(
        self,
        topic_url: str,
        *,
        token: SecretStr | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        try:
            url = httpx.URL(topic_url.strip())
        except httpx.InvalidURL:
            url = httpx.URL()
        if url.scheme not in ("http", "https") or not url.host:
            raise ValueError("ntfy topic url must be an http(s) URL, e.g. https://ntfy.sh/mytopic")
        self._url = topic_url.strip()
        self._token = token
        self._client = client
        self._timeout = timeout_seconds

    async def deliver(self, notice: ExecutionLifecycleNotice) -> None:
        key = LifecycleNoticeRecord(notice=notice).key
        look = _LOOKS[notice.outcome]
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Title": f"Execution {notice.outcome}",
            "Tags": look.tags,
            "Priority": str(look.priority),
            SEQUENCE_ID_HEADER: hashlib.sha256(key.encode()).hexdigest(),
        }
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token.get_secret_value()}"
        body = _message(notice).encode()
        try:
            if self._client is not None:
                # follow_redirects=False per request overrides an injected client's own setting.
                response = await self._client.post(
                    self._url,
                    content=body,
                    headers=headers,
                    timeout=self._timeout,
                    follow_redirects=False,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        self._url, content=body, headers=headers, follow_redirects=False
                    )
        # Not chained: a transport may put request headers (the token) in its
        # message, and the process manager logs this error with its traceback.
        except httpx.RequestError as exc:
            raise LifecycleNoticeUndeliveredError(
                f"lifecycle notice {key} was not delivered to ntfy at "
                f"{httpx.URL(self._url).host}: {type(exc).__name__}; it stays owed"
            ) from None
        if not response.is_success:
            raise LifecycleNoticeUndeliveredError(
                f"lifecycle notice {key} was refused by ntfy at "
                f"{httpx.URL(self._url).host} with HTTP {response.status_code}; it stays owed"
            )
