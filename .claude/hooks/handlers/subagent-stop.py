#!/usr/bin/env python3
"""
SubagentStop Handler - Logs when a subagent completes.

This handler:
1. Receives SubagentStop events from Claude
2. Logs subagent completion metrics
3. Always allows (no blocking)
"""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def log_analytics(event: dict[str, Any]) -> None:
    """Log to analytics file. Fail-safe - never blocks."""
    try:
        path = Path(os.getenv("ANALYTICS_PATH", ".agentic/analytics/events.jsonl"))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps({"timestamp": datetime.now(UTC).isoformat(), **event}) + "\n")
    except Exception:
        pass  # Never block on analytics failure


def main() -> None:
    """Main entry point."""
    try:
        input_data = ""
        if not sys.stdin.isatty():
            input_data = sys.stdin.read()

        if not input_data:
            return

        event = json.loads(input_data)

        log_analytics(
            {
                "event_type": "hook_decision",
                "handler": "subagent-stop",
                "hook_event": event.get("hook_event_name", "SubagentStop"),
                "session_id": event.get("session_id"),
                "subagent_id": event.get("subagent_id"),
                "audit": {
                    "transcript_path": event.get("transcript_path"),
                    "cwd": event.get("cwd"),
                },
            }
        )

    except Exception:
        pass  # Silent fail - subagent stop events don't block


if __name__ == "__main__":
    main()
