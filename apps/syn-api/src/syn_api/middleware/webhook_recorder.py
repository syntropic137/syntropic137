"""ASGI middleware that records incoming GitHub webhooks to JSONL files.

Activated by setting ``SYN_RECORD_WEBHOOKS=true``.  Captures incoming
``POST /webhooks/github`` requests to timestamped JSONL files following
the same convention as SessionRecorder from agentic-primitives.

Output directory: ``fixtures/webhooks/`` (relative to working directory).

Each JSONL file has:
- Line 1: metadata header (start time, event type, source)
- Line 2+: event entries with ``_offset_ms`` for timing replay

Only GitHub-specific headers are recorded — no Authorization or cookie leaks.

See ADR-041: Offline Development Mode and Webhook Recording.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

# GitHub headers worth preserving (lowercase for comparison)
_GITHUB_HEADERS = frozenset(
    {
        "x-github-event",
        "x-github-delivery",
        "x-hub-signature-256",
        "x-github-hook-id",
        "x-github-hook-installation-target-id",
        "x-github-hook-installation-target-type",
        "content-type",
    }
)

_OUTPUT_DIR = Path("fixtures/webhooks")


def _filter_github_headers(scope: Scope) -> dict[str, str]:
    """Extract only GitHub-relevant headers from the ASGI scope."""
    headers: dict[str, str] = {}
    for key_bytes, val_bytes in scope.get("headers", []):
        key = key_bytes.decode("latin-1").lower()
        if key in _GITHUB_HEADERS:
            headers[key] = val_bytes.decode("latin-1")
    return headers


def _parse_payload(body: bytes) -> dict[str, object]:
    """Parse request body as JSON, falling back to raw string."""
    try:
        return json.loads(body)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"_raw": body.decode("utf-8", errors="replace")}


def _build_recording(
    headers: dict[str, str],
    payload: dict[str, object],
    start_ts: datetime,
    elapsed_ms: int,
) -> tuple[Path, dict[str, object], dict[str, object]]:
    """Build the JSONL filepath, metadata line, and event entry."""
    event_type = headers.get("x-github-event", "unknown")
    delivery_id = headers.get("x-github-delivery", "")
    action = payload.get("action", "")
    compound_event = f"{event_type}.{action}" if action else event_type

    date_str = start_ts.strftime("%Y%m%d_%H%M%S")
    filename = f"webhooks_{date_str}_{compound_event.replace('.', '_')}.jsonl"

    metadata: dict[str, object] = {
        "_type": "metadata",
        "recorded_at": start_ts.isoformat(),
        "event_type": event_type,
        "compound_event": compound_event,
        "delivery_id": delivery_id,
        "source": "webhook_recorder",
    }
    event_entry: dict[str, object] = {
        "_offset_ms": elapsed_ms,
        "headers": headers,
        "body": payload,
    }
    return _OUTPUT_DIR / filename, metadata, event_entry


class WebhookRecorderMiddleware:
    """ASGI middleware to record GitHub webhook requests to JSONL.

    Only intercepts ``POST /webhooks/github`` — all other requests pass through.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")

        if method != "POST" or path != "/webhooks/github":
            await self.app(scope, receive, send)
            return

        body_chunks: list[bytes] = []

        async def recording_receive() -> Message:
            message = await receive()
            if message.get("type") == "http.request":
                body_chunks.append(message.get("body", b""))
            return message

        headers = _filter_github_headers(scope)
        start_time = time.monotonic()
        start_ts = datetime.now(tz=UTC)

        await self.app(scope, recording_receive, send)

        body = b"".join(body_chunks)
        payload = _parse_payload(body)
        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        filepath, metadata, event_entry = _build_recording(
            headers, payload, start_ts, elapsed_ms
        )

        with filepath.open("w") as f:
            f.write(json.dumps(metadata) + "\n")
            f.write(json.dumps(event_entry) + "\n")

        import logging

        logging.getLogger(__name__).info("Recorded webhook to %s", filepath)
