#!/usr/bin/env python3
"""
PreToolUse Handler - Routes tool validation to atomic validators.

This handler:
1. Receives PreToolUse events from Claude
2. Determines which validators to run based on tool_name
3. Calls validators in-process (no subprocess)
4. Logs decisions to analytics
5. Returns allow/block decision
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# === VALIDATOR COMPOSITION ===
# Map tool names to validator modules
TOOL_VALIDATORS: dict[str, list[str]] = {
    "Bash": ["security.bash"],
    "Write": ["security.file"],
    "Edit": ["security.file"],
    "Read": ["security.file"],
    "MultiEdit": ["security.file"],
}


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


def load_validator(validator_name: str, validators_dir: Path):
    """Dynamically load a validator module."""
    module_path = validators_dir / (validator_name.replace(".", "/") + ".py")

    if not module_path.exists():
        return None

    import importlib.util

    spec = importlib.util.spec_from_file_location(validator_name, module_path)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return None


def run_validators(tool_name: str, tool_input: dict, context: dict) -> dict:
    """Run all validators for a tool, return first failure or success."""
    validator_names = TOOL_VALIDATORS.get(tool_name, [])

    if not validator_names:
        return {"safe": True, "reason": None, "validators_run": []}

    validators_dir = Path(__file__).parent.parent / "validators"
    validators_run = []

    for validator_name in validator_names:
        module = load_validator(validator_name, validators_dir)
        if module and hasattr(module, "validate"):
            validators_run.append(validator_name)
            result = module.validate(tool_input, context)
            if not result.get("safe", True):
                result["validators_run"] = validators_run
                return result

    return {"safe": True, "reason": None, "validators_run": validators_run}


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
        tool_input = event.get("tool_input", {})
        context = {
            "session_id": event.get("session_id"),
            "tool_use_id": event.get("tool_use_id"),
            "hook_event_name": event.get("hook_event_name", "PreToolUse"),
        }

        # Extract audit context for traceability
        audit = extract_audit_context(event)

        # Run validators
        result = run_validators(tool_name, tool_input, context)
        decision = "block" if not result.get("safe", True) else "allow"

        # Log to analytics with audit trail
        analytics_event = {
            "event_type": "hook_decision",
            "handler": "pre-tool-use",
            "hook_event": context.get("hook_event_name"),  # Claude's hook event type
            "tool_name": tool_name,
            "tool_input_preview": json.dumps(tool_input)[:200] if tool_input else None,
            "decision": decision,
            "reason": result.get("reason"),
            "session_id": context.get("session_id"),
            "tool_use_id": context.get("tool_use_id"),
            "validators_run": result.get("validators_run", []),
            "metadata": result.get("metadata"),
        }
        if audit:
            analytics_event["audit"] = audit
        log_analytics(analytics_event)

        # Output response
        response: dict[str, Any] = {"decision": decision}
        if result.get("reason"):
            response["reason"] = result["reason"]

        print(json.dumps(response))

    except Exception as e:
        # Fail open - allow on error
        print(json.dumps({"decision": "allow", "error": str(e)}))


if __name__ == "__main__":
    main()
