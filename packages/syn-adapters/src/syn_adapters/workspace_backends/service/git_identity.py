"""The GitHub App's git identity, as setup script lines.

Written into the script, never into the setup environment: every value there
is registered for redaction, and agentic-workspace refuses a value holding `[`
or `]`, the ends of its `[REDACTED]` marker. ``<app>[bot]`` always does, so
delivering it as env failed every setup run on 1.0.4-beta.1. It is public.
"""

from __future__ import annotations

import shlex

_FALLBACK_EMAIL = "agent@agentic.local"


def git_identity_lines(name: str | None, email: str | None) -> list[str]:
    """``git config`` lines for `name`, or none when there is no identity."""
    if not name:
        return []
    return [
        "",
        f"git config --global user.name {shlex.quote(name)}",
        f"git config --global user.email {shlex.quote(email or _FALLBACK_EMAIL)}",
    ]
