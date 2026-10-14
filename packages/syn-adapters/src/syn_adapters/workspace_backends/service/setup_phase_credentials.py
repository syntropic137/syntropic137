"""Every credential value the setup phase puts in a workspace (#1927).

What the agent's output must never carry: the stream boundary and artifact
collection withhold each one. Kept apart from ``setup_phase_secrets``, which
says how the values are injected; this says which of them are secret.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets


def file_credential_values(contents: str) -> list[str]:
    """Every string in a credential file, or the whole file when it is not JSON.

    EVERY STRING, HOWEVER SHORT: the injector writes the file as given and
    accepts a value of any length, so no length says a string is not a
    credential. A short label in the file ("apikey") is redacted too; that
    costs a word of output, and guessing the other way leaks a credential.
    """
    try:
        document: object = json.loads(contents)
    except ValueError:
        return [contents.strip()]
    found: list[str] = []
    pending: list[object] = [document]
    while pending:
        node = pending.pop()
        if isinstance(node, str):
            found.append(node)
        elif isinstance(node, dict):
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return found


def credential_values(secrets: SetupPhaseSecrets) -> tuple[str, ...]:
    """Every credential value ``secrets`` puts in the workspace, file contents included."""
    values = [
        *secrets.repo_tokens.values(),
        secrets.gh_token,
        secrets.claude_code_oauth_token,
        secrets.anthropic_api_key,
    ]
    if secrets.codex_auth_json:
        values.extend(file_credential_values(secrets.codex_auth_json))
    return tuple(v for v in values if v)
