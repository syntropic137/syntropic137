#!/usr/bin/env python3
"""
SessionStart Handler - Logs when a session starts.

This handler:
1. Receives SessionStart events from Claude
2. Logs session initialization metrics
3. Always allows (no blocking on session events)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def log_analytics(event: dict[str, Any]) -> None:
    """Log to analytics file. Fail-safe - never blocks."""
    try:
        path = Path(os.getenv("ANALYTICS_PATH", ".agentic/analytics/events.jsonl"))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(
                json.dumps(
                    {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
                )
                + "\n"
            )
    except Exception:
        pass


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
                "event_type": "session_start",
                "handler": "session-start",
                "hook_event": event.get("hook_event_name", "SessionStart"),
                "session_id": event.get("session_id"),
                "start_type": event.get("matcher"),  # startup, resume, clear, compact
                "audit": {
                    "transcript_path": event.get("transcript_path"),
                    "cwd": event.get("cwd"),
                },
            }
        )

    except Exception:
        pass  # Silent fail - session events don't block


if __name__ == "__main__":
    main()
