"""Execution lifecycle webhook settings (#1661).

When both variables are set, the platform POSTs a signed notice to the URL each
time an execution completes, fails or is cancelled. The signature is an
HMAC-SHA256 of the body, keyed by the secret; see
``syn_adapters.execution_lifecycle.webhook_sink``.

**Opt-in, default OFF.** Both unset means the feature is off. Exactly one set
is an error naming the missing one: a URL with no secret would send forgeable
notices, and a secret with no URL is a webhook the operator believes is on.

Environment Variables:
    SYN_LIFECYCLE_WEBHOOK_URL - where notices are POSTed (http or https)
    SYN_LIFECYCLE_WEBHOOK_SECRET - the shared HMAC key
"""

from __future__ import annotations

from typing import NamedTuple, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_SYN_LIFECYCLE_WEBHOOK_URL = "SYN_LIFECYCLE_WEBHOOK_URL"
ENV_SYN_LIFECYCLE_WEBHOOK_SECRET = "SYN_LIFECYCLE_WEBHOOK_SECRET"

_SCHEMES = frozenset({"http", "https"})


class LifecycleWebhook(NamedTuple):
    """A configured webhook: both halves, so a caller cannot hold just one."""

    url: str
    secret: SecretStr


class LifecycleWebhookSettings(BaseSettings):
    """Where execution lifecycle notices go, and the key they are signed with.

    Override via ``SYN_LIFECYCLE_WEBHOOK_*`` environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_LIFECYCLE_WEBHOOK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # A URL can carry a credential (userinfo, a token in the query), and
        # pydantic appends the rejected input to every validation error.
        hide_input_in_errors=True,
    )

    url: str | None = Field(
        default=None,
        description=(
            "URL that receives one signed POST each time an execution completes, "
            "fails or is cancelled (#1661). http or https. Leave EMPTY to disable "
            "(the default). Requires SYN_LIFECYCLE_WEBHOOK_SECRET. "
            "Example: https://hooks.example.com/syn"
        ),
    )

    secret: SecretStr | None = Field(
        default=None,
        description=(
            "Shared secret that keys the X-Syn-Signature-256 HMAC-SHA256 on every "
            "lifecycle notice. Handled as a credential: never logged. Required "
            "when SYN_LIFECYCLE_WEBHOOK_URL is set."
        ),
    )

    @field_validator("url", mode="before")
    @classmethod
    def _blank_url_is_unset(cls, v: object) -> object:
        """``SYN_LIFECYCLE_WEBHOOK_URL=`` in a copied .env.example means off, not on."""
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("secret", mode="before")
    @classmethod
    def _blank_secret_is_unset(cls, v: object) -> object:
        """A blank secret means off; any other secret is kept byte for byte.

        The secret is an opaque HMAC key, and the receiver verifies with the
        value the operator configured. Stripping it would sign with a different
        key and every notice would fail verification.
        """
        raw = v.get_secret_value() if isinstance(v, SecretStr) else v
        if isinstance(raw, str) and not raw.strip():
            return None
        return v

    @field_validator("url")
    @classmethod
    def _http_or_https(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parts = urlsplit(v)
        if parts.scheme not in _SCHEMES or not parts.hostname:
            # The scheme alone is named, never the value: see hide_input_in_errors.
            raise ValueError(
                f"{ENV_SYN_LIFECYCLE_WEBHOOK_URL} must be an http or https URL with a "
                f"host, not one with scheme {parts.scheme!r}"
            )
        return v

    @model_validator(mode="after")
    def _both_or_neither(self) -> Self:
        if self.url is not None and self.secret is None:
            raise ValueError(
                f"{ENV_SYN_LIFECYCLE_WEBHOOK_URL} is set but "
                f"{ENV_SYN_LIFECYCLE_WEBHOOK_SECRET} is not; set both to sign "
                "lifecycle notices, or neither to turn them off"
            )
        if self.secret is not None and self.url is None:
            raise ValueError(
                f"{ENV_SYN_LIFECYCLE_WEBHOOK_SECRET} is set but "
                f"{ENV_SYN_LIFECYCLE_WEBHOOK_URL} is not; set both to send "
                "lifecycle notices, or neither to turn them off"
            )
        return self

    @property
    def webhook(self) -> LifecycleWebhook | None:
        """The configured webhook, or None when the feature is off."""
        if self.url is None or self.secret is None:
            return None
        return LifecycleWebhook(self.url, self.secret)
