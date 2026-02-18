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

        # Collect request body
        body_chunks: list[bytes] = []

        async def recording_receive() -> Message:
            message = await receive()
            if message.get("type") == "http.request":
                body_chunks.append(message.get("body", b""))
            return message

        # Extract headers
        raw_headers: dict[str, str] = {}
        for key_bytes, val_bytes in scope.get("headers", []):
            key = key_bytes.decode("latin-1").lower()
            if key in _GITHUB_HEADERS:
                raw_headers[key] = val_bytes.decode("latin-1")

        start_time = time.monotonic()
        start_ts = datetime.now(tz=UTC)

        # Pass through to the real app
        await self.app(scope, recording_receive, send)

        # Record after the request completes
        body = b"".join(body_chunks)
        event_type = raw_headers.get("x-github-event", "unknown")
        delivery_id = raw_headers.get("x-github-delivery", "")

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {"_raw": body.decode("utf-8", errors="replace")}

        action = payload.get("action", "")
        compound_event = f"{event_type}.{action}" if action else event_type

        # Build JSONL file
        date_str = start_ts.strftime("%Y%m%d_%H%M%S")
        filename = f"webhooks_{date_str}_{compound_event.replace('.', '_')}.jsonl"
        filepath = _OUTPUT_DIR / filename

        metadata = {
            "_type": "metadata",
            "recorded_at": start_ts.isoformat(),
            "event_type": event_type,
            "compound_event": compound_event,
            "delivery_id": delivery_id,
            "source": "webhook_recorder",
        }

        event_entry = {
            "_offset_ms": int((time.monotonic() - start_time) * 1000),
            "headers": raw_headers,
            "body": payload,
        }

        with filepath.open("w") as f:
            f.write(json.dumps(metadata) + "\n")
            f.write(json.dumps(event_entry) + "\n")

        import logging

        logging.getLogger(__name__).info("Recorded webhook to %s", filepath)
