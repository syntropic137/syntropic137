#!/usr/bin/env python3
"""
UserPromptSubmit Handler - Validates user prompts before submission.

This handler:
1. Receives UserPromptSubmit events from Claude
2. Runs prompt validators (PII detection, etc.)
3. Returns allow/block decision
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# === VALIDATOR COMPOSITION ===
# Validators to run on user prompts
PROMPT_VALIDATORS: list[str] = [
    "prompt.pii",
]


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


def run_validators(prompt: str, context: dict) -> dict:
    """Run all prompt validators, return first failure or success."""
    validators_dir = Path(__file__).parent.parent / "validators"
    validators_run = []

    for validator_name in PROMPT_VALIDATORS:
        module = load_validator(validator_name, validators_dir)
        if module and hasattr(module, "validate"):
            validators_run.append(validator_name)
            # For prompt validators, we pass the prompt as tool_input
            result = module.validate({"prompt": prompt}, context)
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

        # Extract prompt - could be in different fields
        prompt = event.get("prompt", event.get("message", event.get("content", "")))
        context = {
            "session_id": event.get("session_id"),
            "hook_event_name": event.get("hook_event_name", "UserPromptSubmit"),
        }

        # Extract audit context for traceability
        audit = extract_audit_context(event)

        # Run validators
        result = run_validators(prompt, context)
        decision = "block" if not result.get("safe", True) else "allow"

        # Log to analytics with audit trail
        analytics_event = {
            "event_type": "hook_decision",
            "handler": "user-prompt",
            "hook_event": context.get("hook_event_name"),  # Claude's hook event type
            "decision": decision,
            "reason": result.get("reason"),
            "session_id": context.get("session_id"),
            "validators_run": result.get("validators_run", []),
            "prompt_length": len(prompt) if prompt else 0,
            "prompt_preview": prompt[:100] if prompt else None,  # First 100 chars
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
