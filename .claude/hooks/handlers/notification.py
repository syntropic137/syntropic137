#!/usr/bin/env python3
"""
Notification Handler - Logs various notifications.

This handler:
1. Receives Notification events from Claude
2. Logs notification events for analytics
3. Always allows (no blocking on notifications)
"""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def log_analytics(event: dict[str, Any]) -> None:
    """Log analytics event to file, silently ignoring failures."""
    try:
        path = Path(os.getenv("ANALYTICS_PATH", ".agentic/analytics/events.jsonl"))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps({"timestamp": datetime.now(UTC).isoformat(), **event}) + "\n")
    except Exception:
        pass  # Analytics must never block


def main() -> None:
    """Main entry point."""
    try:
        input_data = ""
        if not sys.stdin.isatty():
            input_data = sys.stdin.read()

        if not input_data:
            return  # No response needed for non-blocking events

        event = json.loads(input_data)

        log_analytics(
            {
                "event_type": "notification",
                "handler": "notification",
                "hook_event": event.get("hook_event_name", "Notification"),
                "session_id": event.get("session_id"),
                "notification_type": event.get(
                    "matcher",
                ),  # permission_prompt, idle_prompt, error, warning
                "message": event.get("message"),
                "audit": {
                    "transcript_path": event.get("transcript_path"),
                    "cwd": event.get("cwd"),
                },
            },
        )

    except Exception:
        pass  # Notification events must never block


if __name__ == "__main__":
    main()
