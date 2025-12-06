#!/usr/bin/env python3
"""
File Operations Validator

Atomic validator that checks file operations for security issues.
Pure function - no side effects, no analytics, no stdin/stdout handling.
"""

import hashlib
import re
from pathlib import Path
from typing import Any

# Paths that should never be written to
# Include both symlink paths (Linux) and real paths (macOS /private/etc)
BLOCKED_PATHS: list[str] = [
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    "/etc/hosts",
    "/private/etc/passwd",
    "/private/etc/shadow",
    "/private/etc/sudoers",
    "/private/etc/hosts",
    "/boot/",
    "/proc/",
    "/sys/",
    "/dev/",
]

# Paths that require extra scrutiny (warn but don't block)
SENSITIVE_PATHS: list[str] = [
    "/etc/",
    "/var/log/",
    "/tmp/",
    "/usr/",
    "/opt/",
    "~/.ssh/",
    "~/.gnupg/",
    "~/.aws/",
    "~/.config/",
]

# File patterns that should never be read/written by AI
SENSITIVE_FILE_PATTERNS: list[tuple[str, str]] = [
    (r"\.env(?:\.local|\.production|\.staging)?$", "environment file"),
    (r"\.pem$", "PEM certificate/key"),
    (r"\.key$", "private key"),
    (r"id_rsa(?:\.pub)?$", "SSH key"),
    (r"id_ed25519(?:\.pub)?$", "SSH key"),
    (r"\.p12$", "PKCS12 certificate"),
    (r"\.pfx$", "PFX certificate"),
    (r"credentials(?:\.json)?$", "credentials file"),
    (r"secrets\.ya?ml$", "secrets file"),
    (r"\.htpasswd$", "htpasswd file"),
    (r"\.netrc$", "netrc file"),
    (r"\.npmrc$", "npm config (may contain tokens)"),
    (r"\.pypirc$", "pypi config (may contain tokens)"),
    (r"\.aws/", "AWS config directory"),
]

# Content patterns that indicate sensitive data
SENSITIVE_CONTENT_PATTERNS: list[tuple[str, str]] = [
    (r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "private key"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    (r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36}", "GitHub token"),
    (r"sk-[A-Za-z0-9]{48}", "OpenAI API key"),
    (r"xox[baprs]-[0-9A-Za-z-]+", "Slack token"),
]


def hash_content(content: str) -> str:
    """Create a hash of content for logging without exposing the content."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def check_path_blocked(file_path: str) -> tuple[bool, str | None]:
    """Check if a path is in the blocked list."""
    normalized = str(Path(file_path).expanduser().resolve())

    for blocked in BLOCKED_PATHS:
        if normalized.startswith(blocked) or normalized == blocked.rstrip("/"):
            return True, f"Blocked path: {blocked}"

    return False, None


def check_path_sensitive(file_path: str) -> tuple[bool, str | None]:
    """Check if a path is sensitive (warn but don't block)."""
    normalized = str(Path(file_path).expanduser().resolve())

    for sensitive in SENSITIVE_PATHS:
        expanded = str(Path(sensitive).expanduser())
        if normalized.startswith(expanded):
            return True, f"Sensitive path: {sensitive}"

    return False, None


def check_file_pattern(file_path: str) -> tuple[bool, str | None]:
    """Check if filename or path matches sensitive patterns."""
    filename = Path(file_path).name

    for pattern, description in SENSITIVE_FILE_PATTERNS:
        # Check filename first
        if re.search(pattern, filename, re.IGNORECASE):
            return True, f"Sensitive file type: {description}"
        # Also check full path for directory-based patterns (e.g., .aws/)
        if re.search(pattern, file_path, re.IGNORECASE):
            return True, f"Sensitive file type: {description}"

    return False, None


def check_content_sensitive(content: str | None) -> tuple[bool, str | None, str | None]:
    """Check if content contains sensitive patterns. Returns (is_sensitive, reason, hash)."""
    if not content:
        return False, None, None

    for pattern, description in SENSITIVE_CONTENT_PATTERNS:
        if re.search(pattern, content):
            return True, f"Content contains: {description}", hash_content(content)

    return False, None, None


def validate(
    tool_input: dict[str, Any], context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Validate a file operation for security issues.

    Args:
        tool_input: {
            "file_path": "path/to/file",  # or "path" or "target_file"
            "content": "file content",     # optional, for write operations
            "command": "Read|Write|Edit"   # optional, operation type
        }
        context: Optional context

    Returns:
        {"safe": bool, "reason": str | None, "metadata": dict | None}
    """
    # Extract file path from various possible field names
    file_path = tool_input.get(
        "file_path", tool_input.get("path", tool_input.get("target_file", ""))
    )
    content = tool_input.get("content", tool_input.get("new_content", ""))

    if not file_path:
        return {"safe": True}

    metadata: dict[str, Any] = {"file_path": file_path}

    # Check blocked paths (hard block)
    is_blocked, reason = check_path_blocked(file_path)
    if is_blocked:
        return {
            "safe": False,
            "reason": reason,
            "metadata": {**metadata, "risk_level": "critical"},
        }

    # Check sensitive file patterns (hard block for writes)
    is_sensitive_file, file_reason = check_file_pattern(file_path)
    if is_sensitive_file:
        # For read operations on sensitive files, redact instead of block
        operation = tool_input.get(
            "command", context.get("tool_name", "") if context else ""
        )
        if operation in ("Read", "read"):
            return {
                "safe": True,
                "reason": None,
                "metadata": {
                    **metadata,
                    "redacted": True,
                    "redact_reason": file_reason,
                    "content_hash": hash_content(content) if content else None,
                },
            }
        # Block writes to sensitive files
        return {
            "safe": False,
            "reason": file_reason,
            "metadata": {**metadata, "risk_level": "high"},
        }

    # Check content for sensitive data (for write operations)
    if content:
        is_sensitive_content, content_reason, content_hash = check_content_sensitive(
            content
        )
        if is_sensitive_content:
            return {
                "safe": False,
                "reason": f"Cannot write sensitive content: {content_reason}",
                "metadata": {
                    **metadata,
                    "content_hash": content_hash,
                    "risk_level": "high",
                },
            }

    # Check sensitive paths (warn but allow)
    is_sensitive_path, path_reason = check_path_sensitive(file_path)
    if is_sensitive_path:
        metadata["warning"] = path_reason
        metadata["risk_level"] = "medium"

    return {"safe": True, "reason": None, "metadata": metadata if metadata else None}


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
