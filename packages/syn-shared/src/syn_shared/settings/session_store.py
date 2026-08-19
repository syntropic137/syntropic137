"""Central session-store settings (SeshMagic capture).

Syntropic137 can forward every agent session it runs to a central SeshMagic
session store. The capture itself is implemented by a capability that ships in
the agentic-primitives workspace image and activates purely from environment
variables; Syn137's only job is to supply the contract at provision time.

**This is opt-in and defaults to completely OFF.** Syntropic137 must stay
deployable as a full self-hosted stack by operators who have no SeshMagic
instance. When ``SYN_SESSION_STORE_URL`` is unset, no session-store variable is
written into the workspace container at all — not even ``PROVIDER=none`` — and
the capability is a total no-op inside the container.

Environment Variables:
    SYN_SESSION_STORE_* — session store configuration (host side)

Usage:
    from syn_shared.settings import get_settings

    session_store = get_settings().session_store
    if session_store.is_enabled:
        ...
"""

from __future__ import annotations

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Host-side environment variable names, declared once so tooling that has to
#: name them (the 1Password exporter, env checks) does not re-spell them as
#: literals. The prefix below and these names must stay in step.
ENV_SYN_SESSION_STORE_URL = "SYN_SESSION_STORE_URL"
ENV_SYN_SESSION_STORE_AUTH_TOKEN = "SYN_SESSION_STORE_AUTH_TOKEN"

#: Provider identifier understood by the capability inside the workspace image.
SESHMAGIC_PROVIDER = "seshmagic"

#: Container-local spool directory the capability writes sessions to before
#: uploading. Deliberately NOT a mounted volume for this first integration —
#: see the note in the workspace adapter for the durability tradeoff.
DEFAULT_SPOOL_DIR = "/spool"


class SessionStoreSettings(BaseSettings):
    """Configuration for forwarding agent sessions to a central session store.

    Override via ``SYN_SESSION_STORE_*`` environment variables.

    Example:
        # Disabled (the default — nothing is injected into containers)
        # SYN_SESSION_STORE_URL unset

        # Enabled
        SYN_SESSION_STORE_URL=https://sessions.example.com
        SYN_SESSION_STORE_AUTH_TOKEN=<write token>
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_SESSION_STORE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    url: str | None = Field(
        default=None,
        description=(
            "Base URL of the central SeshMagic session store. "
            "Leave EMPTY to disable session capture entirely (the default). "
            "When empty, no session-store variables are injected into workspace "
            "containers and behaviour is identical to having no store at all. "
            "Example: https://sessions.example.com"
        ),
    )

    auth_token: SecretStr | None = Field(
        default=None,
        description=(
            "Write token for the session store. Handled as a credential: never "
            "logged, never included in exception messages, never written to "
            "container labels. Only used when SYN_SESSION_STORE_URL is set."
        ),
    )

    provider: str = Field(
        default=SESHMAGIC_PROVIDER,
        description=(
            "Session store provider implementation the in-container capability "
            "should use. Default: seshmagic."
        ),
    )

    spool_dir: str = Field(
        default=DEFAULT_SPOOL_DIR,
        description=(
            "Directory INSIDE the workspace container where sessions are spooled "
            "before upload. Container-local by design; not a mounted volume. "
            "Default: /spool"
        ),
    )

    @field_validator("url", "auth_token", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: object) -> object:
        """Treat an empty/whitespace-only env var as unset.

        ``SYN_SESSION_STORE_URL=`` in a .env template must mean "disabled", not
        "enabled with an empty URL" — otherwise the generated .env.example would
        silently switch capture on for every self-hoster.
        """
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("provider", mode="before")
    @classmethod
    def _blank_provider_to_default(cls, v: object) -> object:
        """A blank override falls back to the default rather than an empty provider."""
        if isinstance(v, str) and not v.strip():
            return SESHMAGIC_PROVIDER
        return v

    @field_validator("spool_dir", mode="before")
    @classmethod
    def _blank_spool_to_default(cls, v: object) -> object:
        """A blank override falls back to the default rather than an empty path."""
        if isinstance(v, str) and not v.strip():
            return DEFAULT_SPOOL_DIR
        return v

    @property
    def is_enabled(self) -> bool:
        """True only when a store URL is configured.

        The token is intentionally NOT part of this check: an unauthenticated
        store is a legitimate deployment, and a missing token must not silently
        disable capture for an operator who configured a URL.
        """
        return bool(self.url and self.url.strip())

    @property
    def is_unauthenticated(self) -> bool:
        """True when a store URL is set but no write token is.

        This is a LEGITIMATE configuration - an open store on a trusted network
        is a real deployment - so it is deliberately not an error and does not
        disable capture.

        It is surfaced because it is also the shape of the most common
        misconfiguration, and the failure mode is silent: the capability's
        preflight probes an UNAUTHENTICATED health endpoint, so every check
        passes, the workspace starts normally, and the write is rejected with
        401 only at finalize - where the exporter's diagnostic is deliberately
        suppressed to avoid leaking the credential. The operator sees a bare
        failure count with no cause.

        Callers should warn on this at startup. It must never silently disable
        capture for an operator who deliberately configured an open store.
        """
        return self.is_enabled and not self.auth_value

    @property
    def auth_value(self) -> str:
        """The write token as a plain string, or empty when unset.

        Call this only at the point the value is handed to the container
        environment. Never log or interpolate the result anywhere else.
        """
        if self.auth_token is None:
            return ""
        return self.auth_token.get_secret_value()
