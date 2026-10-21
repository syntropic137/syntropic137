"""The head of the setup script: the shell preamble and the GitHub App's git identity.

The identity is written into the script, never into the setup environment:
every value there is registered for redaction, and agentic-workspace refuses a
value holding `[` or `]`, the ends of its `[REDACTED]` marker. ``<app>[bot]``
always does, so delivering it as env failed every setup run on 1.0.4-beta.1.
It is public, so the script is the right place for it.
"""

from __future__ import annotations

import shlex

DEFAULT_SETUP_SCRIPT = "#!/bin/bash\nset -e\n"
_FALLBACK_EMAIL = "agent@agentic.local"


def setup_script_header(name: str | None, email: str | None) -> list[str]:
    """The preamble, then ``git config`` lines for `name` when there is one."""
    lines = [DEFAULT_SETUP_SCRIPT.rstrip()]
    if name:
        lines.append("")
        lines.append(f"git config --global user.name {shlex.quote(name)}")
        lines.append(f"git config --global user.email {shlex.quote(email or _FALLBACK_EMAIL)}")
    return lines
