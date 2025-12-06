#!/usr/bin/env python3
"""
PreCompact Handler - Logs before context compaction.

This handler:
1. Receives PreCompact events from Claude
2. Logs compaction events for analytics
3. Always allows (no blocking on compact events)
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
                "event_type": "pre_compact",
                "handler": "pre-compact",
                "hook_event": event.get("hook_event_name", "PreCompact"),
                "session_id": event.get("session_id"),
                "compact_type": event.get("matcher"),  # manual, auto
                "audit": {
                    "transcript_path": event.get("transcript_path"),
                    "cwd": event.get("cwd"),
                },
            }
        )

    except Exception:
        pass  # Silent fail - compact events don't block


if __name__ == "__main__":
    main()
