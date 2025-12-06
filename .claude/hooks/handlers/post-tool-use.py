#!/usr/bin/env python3
"""
PostToolUse Handler - Logs tool execution results for analytics.

This handler:
1. Receives PostToolUse events from Claude
2. Logs tool execution metadata (duration, success, output preview)
3. Always allows (post-execution, can't block)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# === INLINE ANALYTICS ===
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
        pass  # Never block on analytics failure


def extract_output_preview(tool_result: Any, max_length: int = 200) -> str:
    """Extract a preview of the tool output for logging."""
    if tool_result is None:
        return ""

    if isinstance(tool_result, str):
        output = tool_result
    elif isinstance(tool_result, dict):
        # Try common output fields
        result = (
            tool_result.get("output") or tool_result.get("stdout") or str(tool_result)
        )
        output = str(result)
    else:
        output = str(tool_result)

    if len(output) > max_length:
        return output[:max_length] + "..."
    return output


def extract_audit_context(event: dict[str, Any]) -> dict[str, Any]:
    """Extract audit trail fields from Claude Code event."""
    audit: dict[str, Any] = {}
    if event.get("transcript_path"):
        audit["transcript_path"] = event["transcript_path"]
    if event.get("cwd"):
        audit["cwd"] = event["cwd"]
    if event.get("permission_mode"):
        audit["permission_mode"] = event["permission_mode"]
    return audit


def main() -> None:
    """Main entry point."""
    try:
        # Read event from stdin
        input_data = ""
        if not sys.stdin.isatty():
            input_data = sys.stdin.read()

        if not input_data:
            print(json.dumps({"decision": "allow"}))
            return

        event = json.loads(input_data)

        # Extract fields
        tool_name = event.get("tool_name", "")
        tool_result = event.get("tool_result", {})
        tool_input = event.get("tool_input", {})

        # Extract audit context for traceability
        audit = extract_audit_context(event)

        # Determine success/failure
        is_error = False
        if isinstance(tool_result, dict):
            is_error = tool_result.get("is_error", False) or "error" in tool_result

        # Log to analytics with audit trail
        analytics_event = {
            "event_type": "tool_execution",
            "handler": "post-tool-use",
            "hook_event": event.get(
                "hook_event_name", "PostToolUse"
            ),  # Claude's hook event
            "tool_name": tool_name,
            "session_id": event.get("session_id"),
            "tool_use_id": event.get("tool_use_id"),
            "success": not is_error,
            "output_preview": extract_output_preview(tool_result),
            "input_preview": json.dumps(tool_input)[:200] if tool_input else None,
        }
        if audit:
            analytics_event["audit"] = audit
        log_analytics(analytics_event)

        # Always allow (post-execution)
        print(json.dumps({"decision": "allow"}))

    except Exception as e:
        # Fail open
        print(json.dumps({"decision": "allow", "error": str(e)}))


if __name__ == "__main__":
    main()
