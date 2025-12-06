#!/usr/bin/env python3
"""
PII (Personally Identifiable Information) Validator

Atomic validator that detects PII patterns in user prompts.
Pure function - no side effects, no analytics, no stdin/stdout handling.
"""

import re
from typing import Any

# PII patterns to detect
PII_PATTERNS: list[tuple[str, str, str]] = [
    # SSN (US Social Security Number)
    (r"\b\d{3}-\d{2}-\d{4}\b", "SSN", "high"),
    (r"\b\d{9}\b", "potential SSN (9 digits)", "medium"),
    # Credit card numbers - with or without dashes/spaces
    # Visa: starts with 4, 13-16 digits
    (r"\b4[0-9]{3}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{1,4}\b", "Visa card", "high"),
    (r"\b4[0-9]{12}(?:[0-9]{3})?\b", "Visa card", "high"),
    # Mastercard: starts with 51-55 or 2221-2720, 16 digits
    (
        r"\b5[1-5][0-9]{2}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}\b",
        "Mastercard",
        "high",
    ),
    (r"\b5[1-5][0-9]{14}\b", "Mastercard", "high"),
    # Amex: starts with 34 or 37, 15 digits
    (r"\b3[47][0-9]{2}[-\s]?[0-9]{6}[-\s]?[0-9]{5}\b", "Amex card", "high"),
    (r"\b3[47][0-9]{13}\b", "Amex card", "high"),
    # Discover: starts with 6011, 622126-622925, 644-649, 65, 16 digits
    (
        r"\b6(?:011|5[0-9]{2})[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}\b",
        "Discover card",
        "high",
    ),
    (r"\b6(?:011|5[0-9]{2})[0-9]{12}\b", "Discover card", "high"),
    # Phone numbers (various formats)
    (
        r"\b(?:\+1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
        "US phone number",
        "medium",
    ),
    (
        r"\b\+\d{1,3}[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}\b",
        "international phone",
        "medium",
    ),
    # Email addresses
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "email address", "low"),
    # IP addresses
    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "IP address", "low"),
    # Dates of birth (various formats)
    (
        r"\b(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b",
        "date (MM/DD/YYYY)",
        "low",
    ),
    (
        r"\b(?:19|20)\d{2}[/-](?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])\b",
        "date (YYYY-MM-DD)",
        "low",
    ),
    # Passport numbers (basic patterns)
    (r"\b[A-Z]{1,2}\d{6,9}\b", "potential passport number", "medium"),
    # Driver's license (very generic, state-dependent)
    (r"\b[A-Z]\d{7,8}\b", "potential DL number", "low"),
]

# Patterns that might indicate personal context but aren't PII themselves
CONTEXT_PATTERNS: list[tuple[str, str]] = [
    (r"\bmy\s+(?:ssn|social\s+security)", "SSN context"),
    (r"\bmy\s+(?:credit\s+card|cc\s+number)", "credit card context"),
    (r"\bmy\s+(?:phone|cell|mobile)\s+(?:number|#)", "phone context"),
    (r"\bmy\s+(?:address|home\s+address)", "address context"),
    (r"\bmy\s+(?:password|passwd|pwd)", "password context"),
    (r"\bmy\s+(?:bank\s+account|routing\s+number)", "banking context"),
]


def validate(
    tool_input: dict[str, Any], context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Validate a prompt for PII patterns.

    Args:
        tool_input: {"prompt": "user prompt text"}
        context: Optional context

    Returns:
        {"safe": bool, "reason": str | None, "metadata": dict | None}
    """
    prompt = tool_input.get("prompt", "")

    if not prompt:
        return {"safe": True}

    detected_pii: list[dict[str, str | int]] = []
    highest_risk = "none"
    risk_order = {"none": 0, "low": 1, "medium": 2, "high": 3}

    # Check for PII patterns
    for pattern, pii_type, risk_level in PII_PATTERNS:
        matches = re.findall(pattern, prompt, re.IGNORECASE)
        if matches:
            detected_pii.append(
                {
                    "type": pii_type,
                    "risk": risk_level,
                    "count": len(matches),
                }
            )
            if risk_order.get(risk_level, 0) > risk_order.get(highest_risk, 0):
                highest_risk = risk_level

    # Check for context patterns (these raise awareness but don't block)
    detected_context: list[str] = []
    for pattern, context_type in CONTEXT_PATTERNS:
        if re.search(pattern, prompt, re.IGNORECASE):
            detected_context.append(context_type)

    # Determine action based on risk level
    if highest_risk == "high":
        pii_types = [str(p["type"]) for p in detected_pii if p["risk"] == "high"]
        return {
            "safe": False,
            "reason": f"High-risk PII detected: {', '.join(pii_types)}",
            "metadata": {
                "detected_pii": detected_pii,
                "detected_context": detected_context,
                "risk_level": "high",
                "prompt_length": len(prompt),
            },
        }

    # Medium/low risk: allow but log
    metadata: dict[str, Any] = {
        "risk_level": highest_risk,
        "prompt_length": len(prompt),
    }

    if detected_pii:
        metadata["detected_pii"] = detected_pii

    if detected_context:
        metadata["detected_context"] = detected_context

    return {
        "safe": True,
        "reason": None,
        "metadata": metadata if (detected_pii or detected_context) else None,
    }


# Standalone testing
if __name__ == "__main__":
    import json
    import sys

    input_data = ""
    if not sys.stdin.isatty():
        input_data = sys.stdin.read()

    if input_data:
        tool_input = json.loads(input_data)
        result = validate(tool_input)
        print(json.dumps(result))
    else:
        print(json.dumps({"safe": True, "message": "No input provided"}))
