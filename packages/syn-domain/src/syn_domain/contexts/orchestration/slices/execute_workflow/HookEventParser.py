"""HookEventParser — parses hook events from Claude CLI stream lines.

Two sources:
- Standalone JSONL from Claude Code hooks (parse_jsonl_line)
- hook_response system events with embedded JSONL across 3 channels

Deduplicates via fingerprint set (same event appears as raw stderr
AND inside hook_response envelope in containers).

Extracted from EventStreamProcessor._parse_hook_events() (ISS-196).
"""

from __future__ import annotations

import json
import logging
from typing import Any

# Any: dict[str, Any] used for JSON data from json.loads() (system boundary — external CLI JSONL)
from agentic_events import parse_jsonl_line

logger = logging.getLogger(__name__)


class HookEventParser:
    """Parses and deduplicates hook events from Claude CLI stream lines."""

    def __init__(self) -> None:
        self._seen_fingerprints: set[tuple[str, ...]] = set()

    def parse(self, line: str) -> list[dict[str, Any]]:
        """Parse, deduplicate, return hook events from a single line."""
        raw_events = self._parse_standalone(line)
        if raw_events is None:
            raw_events = self._parse_hook_response(line)
        return self._deduplicate(raw_events)

    def _parse_standalone(self, line: str) -> list[dict[str, Any]] | None:
        """Try parsing as standalone JSONL hook event. Returns None if not a hook event."""
        standalone = parse_jsonl_line(line)
        if standalone:
            return [standalone]
        return None

    def _parse_hook_response(self, line: str) -> list[dict[str, Any]]:
        """Try parsing as a hook_response system event with embedded JSONL."""
        try:
            parsed = json.loads(line)
        except (json.JSONDecodeError, AttributeError):
            return []

        line_type = parsed.get("type", "")
        line_subtype = parsed.get("subtype", "")

        if line_type == "system":
            logger.info(
                "System event: subtype=%s keys=%s",
                line_subtype,
                list(parsed.keys()),
            )

        if line_type != "system" or line_subtype != "hook_response":
            return []

        hook_name = parsed.get("hook_name", "?")
        hook_event = parsed.get("hook_event", "?")
        seen: set[str] = set()
        events: list[dict[str, Any]] = []

        for channel in ("output", "stdout", "stderr"):
            channel_text = parsed.get(channel, "")
            logger.info(
                "hook_response hook=%s event=%s channel=%s len=%d content=%r",
                hook_name,
                hook_event,
                channel,
                len(channel_text),
                channel_text[:300],
            )
            self._extract_events_from_channel(channel_text, seen, events)

        return events

    @staticmethod
    def _extract_events_from_channel(
        channel_text: str,
        seen: set[str],
        events: list[dict[str, Any]],
    ) -> None:
        """Extract hook events from a single hook_response channel."""
        for hook_line in channel_text.splitlines():
            hook_line = hook_line.strip()
            if not hook_line or hook_line in seen:
                continue
            evt = parse_jsonl_line(hook_line)
            if evt:
                seen.add(hook_line)
                events.append(evt)
            else:
                logger.info(
                    "hook_response line not a hook event: %r",
                    hook_line[:200],
                )

    def _deduplicate(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove events already seen (by fingerprint)."""
        result: list[dict[str, Any]] = []
        for event in events:
            fp = self._fingerprint(event)
            if fp not in self._seen_fingerprints:
                self._seen_fingerprints.add(fp)
                result.append(event)
            else:
                logger.debug("Skipping duplicate hook event: %s", fp[0])
        return result

    @staticmethod
    def _fingerprint(event: dict[str, Any]) -> tuple[str, ...]:
        """Build a dedup fingerprint for a hook event."""
        evt_type = event.get("event_type", "")
        evt_sid = event.get("session_id", "")
        evt_ctx = event.get("context") or {}
        evt_tuid = evt_ctx.get("tool_use_id", "")
        if evt_tuid:
            return (
                evt_type,
                evt_sid,
                str(event.get("timestamp", "")),
                evt_tuid,
            )
        return (evt_type, evt_sid)
