"""Decide which credential a codex phase authenticates with (#1971).

Two settings can carry one:

* ``CODEX_AUTH_JSON`` - the full contents of ``~/.codex/auth.json``, normally a
  ChatGPT subscription login.
* ``OPENAI_API_KEY`` - a plain OpenAI API key.

``CODEX_AUTH_JSON`` wins when both are set, mirroring how the Claude path
prefers ``CLAUDE_CODE_OAUTH_TOKEN`` over ``ANTHROPIC_API_KEY``.

WHY THE KEY BECOMES A FILE. Codex reads its credential from
``$CODEX_HOME/auth.json``. The file a key becomes is codex format knowledge, so
it comes from the `CodexCredentialFileFormat` port (`codex_credential_port`),
never from here. Turning the key into that file lets it ride the existing
staging path - staged under ``.setup/``, relocated to ``~/.codex/auth.json`` at
0600, removal verified fail-closed - so it never enters the agent environment,
argv, logs or the setup script text. Codex's own env-var route
(``CODEX_API_KEY``) would put it in the agent environment, which is exactly
what the codex path refuses to do.

No logging: the health probe and the setup phase resolve with one rule and
each caller decides what to report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from syn_shared.codex_auth_file import CODEX_AUTH_FILE_FORMAT

if TYPE_CHECKING:
    from syn_shared.codex_credential_port import CodexCredentialFileFormat
    from syn_shared.settings import Settings


class CodexCredentialSource(StrEnum):
    """Which setting the codex credential came from."""

    CODEX_AUTH_JSON = "codex_auth_json"
    OPENAI_API_KEY = "openai_api_key"


@dataclass(frozen=True)
class ResolvedCodexCredential:
    """The auth.json a codex phase gets, and where it came from.

    ``auth_json`` is secret and is excluded from ``repr`` so the object can be
    logged or appear in a traceback without leaking it.
    """

    auth_json: str = field(repr=False)
    source: CodexCredentialSource
    both_configured: bool
    """True when ``OPENAI_API_KEY`` was set too and lost to ``CODEX_AUTH_JSON``."""


def resolve_codex_credential(
    *,
    codex_auth_json: str | None,
    openai_api_key: str | None,
    credential_format: CodexCredentialFileFormat = CODEX_AUTH_FILE_FORMAT,
) -> ResolvedCodexCredential | None:
    """Apply the precedence: ``CODEX_AUTH_JSON`` first, ``OPENAI_API_KEY`` second.

    Blank values count as unset. Returns None when neither is configured. The
    key becomes a credential file through ``credential_format``, the port that
    owns codex's file format.
    """
    auth_json = codex_auth_json if codex_auth_json and codex_auth_json.strip() else None
    api_key = openai_api_key.strip() if openai_api_key else ""
    if auth_json is not None:
        return ResolvedCodexCredential(
            auth_json=auth_json,
            source=CodexCredentialSource.CODEX_AUTH_JSON,
            both_configured=bool(api_key),
        )
    if api_key:
        return ResolvedCodexCredential(
            auth_json=credential_format.api_key_credential_file(api_key),
            source=CodexCredentialSource.OPENAI_API_KEY,
            both_configured=False,
        )
    return None


def resolve_configured_codex_credential(
    settings: Settings | None = None,
) -> ResolvedCodexCredential | None:
    """`resolve_codex_credential` over the deployment's settings (default: loaded).

    The one place both settings are read, so a codex phase and ``/health``
    cannot disagree about which credential is in force.
    """
    if settings is None:
        from syn_shared.settings import get_settings

        settings = get_settings()
    return resolve_codex_credential(
        codex_auth_json=(
            settings.codex_auth_json.get_secret_value() if settings.codex_auth_json else None
        ),
        openai_api_key=(
            settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        ),
    )
