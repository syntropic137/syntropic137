#!/usr/bin/env python3
"""
Bash Command Validator

Atomic validator that checks shell commands for dangerous patterns.
Pure function - no side effects, no analytics, no stdin/stdout handling.
"""

import re
from typing import Any

# Dangerous patterns that should be blocked
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    # Destructive file operations
    (r"\brm\s+-rf\s+/(?!\w)", "rm -rf / (root deletion)"),
    (r"\brm\s+-rf\s+~", "rm -rf ~ (home deletion)"),
    (r"\brm\s+-rf\s+\*", "rm -rf * (wildcard deletion)"),
    (r"\brm\s+-rf\s+\.\.(?:\s|$)", "rm -rf .. (parent deletion)"),
    (r"\brm\s+-rf\s+\.(?:\s|$)", "rm -rf . (current dir deletion)"),
    # Disk operations
    (r"\bdd\s+if=.*of=/dev/(sd|hd|nvme)", "disk overwrite"),
    (r"\bmkfs\.", "filesystem format"),
    (r">\s*/dev/(sd|hd|nvme)", "direct disk write"),
    # System destruction
    (r":\(\)\s*\{.*:\|:&.*\}", "fork bomb"),
    (r"\bkill\s+-9\s+-1", "kill all processes"),
    (r"\bkillall\s+-9", "killall -9"),
    # Permission chaos
    (r"\bchmod\s+-R\s+777\s+/(?!\w)", "chmod 777 / (insecure permissions)"),
    (r"\bchmod\s+-R\s+000\s+/(?!\w)", "chmod 000 / (lockout)"),
    (r"\bchown\s+-R.*:.*\s+/(?!\w)", "chown -R / (ownership change)"),
    # Remote code execution
    (r"\bcurl.*\|\s*(ba)?sh", "curl pipe to shell"),
    (r"\bwget.*\|\s*(ba)?sh", "wget pipe to shell"),
    (r"\bcurl.*\|\s*python", "curl pipe to python"),
    # Git dangers
    (r"\bgit\s+push\s+.*--force", "force push"),
    (r"\bgit\s+reset\s+--hard\s+origin", "hard reset to origin"),
    (r"\bgit\s+clean\s+-fdx", "git clean all"),
    # Network dangers
    (r"\bnc\s+-l.*-e\s*/bin/(ba)?sh", "netcat shell"),
    (r"\biptables\s+-F", "flush firewall"),
]

# Patterns that warrant a warning but aren't blocked
SUSPICIOUS_PATTERNS: list[tuple[str, str]] = [
    (r"\bsudo\s+", "sudo usage"),
    (r"\bsu\s+-", "switch user"),
    (r"\beval\s+", "eval usage"),
    (r"\bexec\s+", "exec usage"),
    (r">\s*/etc/", "write to /etc"),
    (r"\bsystemctl\s+(stop|disable|mask)", "systemctl stop/disable"),
    (r"\bservice\s+.*stop", "service stop"),
    (r"\benv\s+.*=.*\s+(ba)?sh", "env injection"),
]

# Additional git patterns that should be blocked
GIT_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"\bgit\s+add\s+-A(?:\s|$)", "git add -A (adds all files including secrets)"),
    (r"\bgit\s+add\s+\.(?:\s|$)", "git add . (adds all files including secrets)"),
]


def validate(
    tool_input: dict[str, Any], context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Validate a bash command for dangerous patterns.

    Args:
        tool_input: {"command": "the shell command"}
        context: Optional context (unused in this validator)

    Returns:
        {"safe": bool, "reason": str | None, "metadata": dict | None}
    """
    command = tool_input.get("command", "")

    if not command:
        return {"safe": True}

    # Check dangerous patterns
    for pattern, description in DANGEROUS_PATTERNS + GIT_DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return {
                "safe": False,
                "reason": f"Dangerous command blocked: {description}",
                "metadata": {
                    "pattern": pattern,
                    "command_preview": command[:100],
                    "risk_level": "critical",
                },
            }

    # Check suspicious patterns (don't block, just note in metadata)
    suspicious: list[str] = []
    for pattern, description in SUSPICIOUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            suspicious.append(description)

    return {
        "safe": True,
        "reason": None,
        "metadata": {"suspicious_patterns": suspicious, "risk_level": "low"}
        if suspicious
        else None,
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
        # Interactive test mode
        print(json.dumps({"safe": True, "message": "No input provided"}))
