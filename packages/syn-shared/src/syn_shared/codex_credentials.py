"""Decide which credential a codex phase authenticates with (#1971).

Two settings can carry one:

* ``CODEX_AUTH_JSON`` - the full contents of ``~/.codex/auth.json``, normally a
  ChatGPT subscription login.
* ``OPENAI_API_KEY`` - a plain OpenAI API key.

``CODEX_AUTH_JSON`` wins when both are set, mirroring how the Claude path
prefers ``CLAUDE_CODE_OAUTH_TOKEN`` over ``ANTHROPIC_API_KEY``.

WHY THE KEY BECOMES A FILE. Codex reads its credential from
``$CODEX_HOME/auth.json``; the stored file is what ``codex login --with-api-key``
writes, and it is the shape synthesised here (codex-rs ``login_with_api_key``,
``login/src/auth/manager.rs`` at rust-v0.160.1). Turning the key into that file
lets it ride the existing staging path - staged under ``.setup/``, relocated to
``~/.codex/auth.json`` at 0600, removal verified fail-closed - so it never
enters the agent environment, argv, logs or the setup script text. Codex's own
env-var route (``CODEX_API_KEY``) would put it in the agent environment, which
is exactly what the codex path refuses to do.

No logging: the health probe and the setup phase resolve with one rule and
each caller decides what to report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from syn_shared.settings import Settings

#: The ``auth_mode`` codex writes for an API-key login. codex-rs serialises
#: ``AuthMode::ApiKey`` with ``rename_all = "lowercase"``
#: (``protocol/src/auth.rs`` at rust-v0.160.1).
CODEX_API_KEY_AUTH_MODE: Final = "apikey"


class CodexCredentialSource(StrEnum):
    """Which setting the codex credential came from."""

    CODEX_AUTH_JSON = "codex_auth_json"
    OPENAI_API_KEY = "openai_api_key"


class CodexApiKeyAuthFile(BaseModel):
    """The ``auth.json`` codex writes for ``codex login --with-api-key``.

    Field names are codex's: ``auth_mode`` and the upper-case ``OPENAI_API_KEY``
    (``AuthDotJson`` in ``login/src/auth/storage.rs`` at rust-v0.160.1, which
    renames ``openai_api_key`` to ``OPENAI_API_KEY``). Verified against
    codex-cli 0.160.1, the version the agentic-workspace image pins, on
    2026-10-14 (#1971).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    auth_mode: Literal["apikey"] = CODEX_API_KEY_AUTH_MODE
    openai_api_key: str = Field(serialization_alias="OPENAI_API_KEY", repr=False)


def codex_api_key_auth_json(api_key: str) -> str:
    """The ``auth.json`` text that authenticates codex with ``api_key``.

    Serialised by Pydantic, so a key containing a quote or a backslash is
    escaped rather than breaking the file.
    """
    return CodexApiKeyAuthFile(openai_api_key=api_key).model_dump_json(by_alias=True)


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
    *, codex_auth_json: str | None, openai_api_key: str | None
) -> ResolvedCodexCredential | None:
    """Apply the precedence: ``CODEX_AUTH_JSON`` first, ``OPENAI_API_KEY`` second.

    Blank values count as unset. Returns None when neither is configured.
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
            auth_json=codex_api_key_auth_json(api_key),
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
