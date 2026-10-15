"""The port through which Syntropic137 handles a codex credential file (#1971).

What a codex ``auth.json`` looks like is harness knowledge: it changes when
OpenAI ships a new codex CLI, not when we decide what a credential means. Per
the repository boundary (CLAUDE.md, "Where does this change belong?") that
knowledge belongs in agentic-workspace. This module is the contract the domain
side depends on, so the format lives behind it in exactly one adapter
(`syn_shared.codex_auth_file`) and can move to agentic-workspace without any
caller changing (#1973).

Deployment precedence (which setting wins) is ours, and stays in
`syn_shared.codex_credentials`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class CodexCredentialFileKind(StrEnum):
    """What a codex credential file is, as far as authenticating goes."""

    NOT_JSON = "not_json"
    NOT_AN_OBJECT = "not_an_object"
    MALFORMED = "malformed"
    """A JSON object whose fields do not have the types codex expects."""
    API_KEY = "api_key"
    """API-key auth carrying a usable (non-blank string) key."""
    API_KEY_WITHOUT_KEY = "api_key_without_key"
    """API-key auth with the key missing, null, empty or whitespace: unusable."""
    TOKENS = "tokens"
    """Token-based auth (a ChatGPT login or similar)."""


@dataclass(frozen=True)
class CodexCredentialFileClassification:
    """A non-secret description of a codex credential file."""

    kind: CodexCredentialFileKind
    access_token_expiry: float | None = None
    """For ``TOKENS``: the access token's ``exp`` (epoch seconds), when readable."""


class CodexCredentialFileFormat(Protocol):
    """Serialise and classify codex credential files. Never returns key material."""

    def api_key_credential_file(self, api_key: str) -> str:
        """The credential file text that authenticates codex with ``api_key``."""
        ...

    def classify(self, credential_file: str) -> CodexCredentialFileClassification:
        """Describe ``credential_file`` without raising and without echoing it."""
        ...
