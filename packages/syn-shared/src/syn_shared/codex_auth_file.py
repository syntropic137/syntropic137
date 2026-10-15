"""The codex ``auth.json`` format: the one adapter for `CodexCredentialFileFormat`.

Every fact here about the file is codex CLI knowledge, verified against
openai/codex at ``rust-v0.160.1`` (the codex-cli version the agentic-workspace
image pins) on 2026-10-14:

* ``login/src/auth/storage.rs:39-65``: ``AuthDotJson`` has ``auth_mode``,
  ``OPENAI_API_KEY`` (renamed from ``openai_api_key``), ``tokens``,
  ``last_refresh``, ``agent_identity``, ``personal_access_token``,
  ``bedrock_api_key`` and ``bedrock_access_keys``.
* ``protocol/src/auth.rs:6-11``: ``AuthMode`` is ``rename_all = "lowercase"``,
  so API-key auth is ``"apikey"``.
* ``login/src/auth/manager.rs:1022-1042``: ``codex login --with-api-key`` writes
  ``{"auth_mode": "apikey", "OPENAI_API_KEY": <key>}`` and nothing else.
* ``login/src/auth/manager.rs:1763-1780``: ``resolved_mode`` - an explicit
  ``auth_mode`` decides; otherwise a PAT or Bedrock field wins; otherwise a
  present ``OPENAI_API_KEY`` means API key; otherwise ChatGPT.

TODO(#1973): move this adapter into agentic-workspace beside the codex harness
adapter, where a codex CLI change is caught, and satisfy the port from there.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from syn_shared.codex_credential_port import (
    CodexCredentialFileClassification,
    CodexCredentialFileKind,
)

#: ``AuthMode::ApiKey`` as codex serialises it.
API_KEY_AUTH_MODE: Final = "apikey"

_JWT_SEGMENTS: Final = 3


class CodexApiKeyAuthFile(BaseModel):
    """The file ``codex login --with-api-key`` writes. Written, never read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    auth_mode: Literal["apikey"] = API_KEY_AUTH_MODE
    openai_api_key: str = Field(serialization_alias="OPENAI_API_KEY", repr=False)


class _CodexTokens(BaseModel):
    """``tokens`` in a token-based auth.json. Only the access token is read.

    ``extra="allow"`` because codex's ``TokenData`` also carries ``id_token``,
    ``refresh_token`` and ``account_id``; forbidding them would call every real
    ChatGPT login malformed.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    access_token: str | None = Field(default=None, repr=False)


class _CodexAuthFile(BaseModel):
    """The fields of ``AuthDotJson`` that decide how codex authenticates.

    ``extra="allow"`` because the real file carries more than is read here
    (``last_refresh``, ``agent_identity``) and codex adds fields between
    versions; a reader that forbade them would misreport a valid file. The
    three ``JsonValue`` fields are only tested for presence, as codex does.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    auth_mode: str | None = None
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY", repr=False)
    tokens: _CodexTokens | None = None
    personal_access_token: JsonValue = Field(default=None, repr=False)
    bedrock_api_key: JsonValue = Field(default=None, repr=False)
    bedrock_access_keys: JsonValue = Field(default=None, repr=False)

    def is_api_key_mode(self) -> bool:
        """codex's ``resolved_mode`` reduced to "is it ``ApiKey``"."""
        if self.auth_mode is not None:
            return self.auth_mode == API_KEY_AUTH_MODE
        if any(
            field is not None
            for field in (
                self.personal_access_token,
                self.bedrock_api_key,
                self.bedrock_access_keys,
            )
        ):
            return False
        return self.openai_api_key is not None


def _decode_exp(access_token: str) -> float | None:
    """Read the ``exp`` claim out of a JWT payload. None if it is not one.

    Padding is restored before decoding because JWT segments are base64url with
    padding stripped, which ``urlsafe_b64decode`` rejects.
    """
    if access_token.count(".") != _JWT_SEGMENTS - 1:
        return None
    payload = access_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    try:
        claims: object = json.loads(base64.urlsafe_b64decode(payload))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(claims, dict):
        return None
    exp: object = claims.get("exp")
    return float(exp) if isinstance(exp, (int, float)) else None


class CodexAuthFileFormat:
    """`CodexCredentialFileFormat` for codex-cli 0.160.1's ``auth.json``."""

    def api_key_credential_file(self, api_key: str) -> str:
        """Serialised by Pydantic, so a quote or backslash in the key is escaped."""
        return CodexApiKeyAuthFile(openai_api_key=api_key).model_dump_json(by_alias=True)

    def classify(self, credential_file: str) -> CodexCredentialFileClassification:
        """Never raises. A `ValidationError` is swallowed whole: its text quotes input."""
        try:
            parsed: object = json.loads(credential_file)
        except ValueError:
            return CodexCredentialFileClassification(CodexCredentialFileKind.NOT_JSON)
        if not isinstance(parsed, dict):
            return CodexCredentialFileClassification(CodexCredentialFileKind.NOT_AN_OBJECT)
        try:
            auth = _CodexAuthFile.model_validate(parsed)
        except ValidationError:
            return CodexCredentialFileClassification(CodexCredentialFileKind.MALFORMED)

        if auth.is_api_key_mode():
            usable = auth.openai_api_key is not None and bool(auth.openai_api_key.strip())
            return CodexCredentialFileClassification(
                CodexCredentialFileKind.API_KEY
                if usable
                else CodexCredentialFileKind.API_KEY_WITHOUT_KEY
            )
        access_token = auth.tokens.access_token if auth.tokens is not None else None
        return CodexCredentialFileClassification(
            CodexCredentialFileKind.TOKENS,
            access_token_expiry=_decode_exp(access_token) if access_token else None,
        )


#: The adapter in force. One instance: it holds no state.
CODEX_AUTH_FILE_FORMAT: Final[CodexAuthFileFormat] = CodexAuthFileFormat()
