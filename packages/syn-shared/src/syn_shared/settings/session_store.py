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

import re

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Host-side environment variable names, declared once so tooling that has to
#: name them (the 1Password exporter, env checks) does not re-spell them as
#: literals. The prefix below and these names must stay in step.
ENV_SYN_SESSION_STORE_URL = "SYN_SESSION_STORE_URL"
ENV_SYN_SESSION_STORE_AUTH_TOKEN = "SYN_SESSION_STORE_AUTH_TOKEN"
ENV_SYN_SESSION_STORE_LABEL = "SYN_SESSION_STORE_LABEL"
ENV_SYN_SESSION_STORE_DEPLOYMENT = "SYN_SESSION_STORE_DEPLOYMENT"

#: Provider identifier understood by the capability inside the workspace image.
SESHMAGIC_PROVIDER = "seshmagic"

#: Container-local spool directory the capability writes sessions to before
#: uploading. Deliberately NOT a mounted volume for this first integration —
#: see the note in the workspace adapter for the durability tradeoff.
DEFAULT_SPOOL_DIR = "/spool"

#: What a store label is allowed to be: ASCII letters, digits, dot, underscore
#: and hyphen, 1 to 64 characters.
#:
#: Narrow on purpose. This string exists so an operator can TRUST which store a
#: posture line names, and the threats to that are not only control characters.
#: Printable Unicode carries homoglyphs, combining marks and variation
#: selectors, so a label can render as one store while being another. Rejecting
#: anything outside a plain identifier removes that class entirely, and the
#: length bound stops a pasted blob flooding the line.
#:
#: Enforced by REJECTION, not truncation. Truncating would mean the logged text
#: is not the configured value, which is the opposite of what this field is for.
_LABEL_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")


def usable_label(label: str | None) -> str:
    """The operator's label if it is a usable identifier, otherwise "".

    A module function, not only a property, because a caller may need the label
    rule when the rest of the settings CANNOT be built - a rejected URL must not
    take the label rule down with it, or a malformed label (the case this rule
    exists to catch) escapes the handling that keeps it out of logs.

    `SessionStoreSettings.display_label` delegates here, so there is exactly one
    definition of what a usable label is.
    """
    candidate = (label or "").strip()
    return candidate if _LABEL_PATTERN.fullmatch(candidate) else ""


def usable_deployment(deployment: str | None) -> str:
    """The operator's deployment identity if usable, otherwise "".

    Same rule as `usable_label` and deliberately so: both end up in the startup
    posture line, and the deployment identity additionally travels to the store
    as the ``deployment`` tag, where it is a JOIN KEY. A homoglyph or a stray
    newline in a join key is worse than in a display string - it silently
    partitions one deployment's corpus into two.

    A module function for the same reason `usable_label` is one: a caller may
    need the rule when the rest of the settings cannot be built.
    """
    candidate = (deployment or "").strip()
    return candidate if _LABEL_PATTERN.fullmatch(candidate) else ""


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
        # Pydantic embeds the offending INPUT in ValidationError by default.
        # `_reject_internal_whitespace` raises on the URL, and this class holds
        # that URL precisely because every part of it is operator-supplied and
        # could carry a credential - which is why the startup posture line logs
        # no part of it. Without this, one pasted space defeats that: the
        # validation error prints the whole URL into the startup log. A
        # validator writing a careful message is not enough, the framework
        # appends the input regardless. Mirrors `Settings` in config.py.
        hide_input_in_errors=True,
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

    read_token: SecretStr | None = Field(
        default=None,
        description=(
            "Read token for the session store, used to fetch a delegated "
            "session's transcript back so its cost can be attributed. "
            "SEPARATE from the write token because a conforming store may scope "
            "the two differently - a write-only token returns 401 on reads, and "
            "every delegate then looks like a transient store outage rather "
            "than an auth failure. Falls back to SYN_SESSION_STORE_AUTH_TOKEN "
            "when unset, which is correct for a store that issues one token "
            "carrying both scopes. Handled as a credential."
        ),
    )

    deployment: str = Field(
        default="",
        description=(
            "Overrides the deployment identity this install stamps on every "
            "session it exports, replacing the derived "
            "syntropic137__<APP_ENVIRONMENT>. Set it when two installs share an "
            "APP_ENVIRONMENT but are different deployments - the canonical case "
            "is migrating a selfhost install between hosts, where both the old "
            "and the new one report syntropic137__selfhost and their sessions "
            "become indistinguishable in the corpus during exactly the window "
            "you most want to compare them. This is the deployment's OWN "
            "identity; SYN_SESSION_STORE_LABEL names the store it writes TO. "
            "MUST be a plain identifier: ASCII letters, digits, dot, underscore "
            "and hyphen, 1 to 64 characters (so syntropic137__vps, not "
            "syn/vps). Anything else is IGNORED with a warning that does not "
            "repeat the value, falling back to the derived identity. Applies to "
            "sessions exported AFTER it is set; already-stored sessions keep "
            "the identity they were written with. "
            "Example: syntropic137__vps"
        ),
    )

    label: str = Field(
        default="",
        description=(
            "Short non-secret name for the store this deployment writes to, "
            "shown in the startup posture line. Set it when more than one store "
            "is reachable from the same environment. The posture line "
            "deliberately logs NO part of SYN_SESSION_STORE_URL, because every "
            "part of a URL is operator-supplied and could carry a credential, "
            "so two stores differing only by path are otherwise "
            "indistinguishable. MUST be a plain identifier: ASCII letters, "
            "digits, dot, underscore and hyphen, 1 to 64 characters (so "
            "prod-west, not prod:west or org/tenant, and no accented or "
            "non-ASCII letters). Anything else is IGNORED with a warning that "
            "does not repeat the value, and the line falls back to naming the "
            "deployment alone. Surrounding whitespace is trimmed. Declared "
            "non-secret by the operator rather than derived from a value that "
            "might not be. Do NOT put a token, a password or a full URL here. "
            "Example: tenant-a"
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

    @field_validator("url", "auth_token", "read_token", mode="before")
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

    @field_validator("url", "auth_token", "read_token", mode="before")
    @classmethod
    def _strip_surrounding_whitespace(cls, v: object) -> object:
        """Trim whitespace a human left around a hand-pasted value.

        A trailing space is invisible in a vault UI and in most log output, and
        it does not fail loudly: the URL becomes
        ``http://host:18090 /v1/sessions/batch``, every upload errors, capture
        records FAILED, and because capture is fail-open the workflow still
        goes green. That is exactly the failure shape this whole subsystem is
        built to avoid, so normalise rather than trust the input.

        Observed for real on 2026-08-21: SYN_SESSION_STORE_URL held 27 bytes
        for a 26-byte URL. Reproduced directly - the trailing space returned a
        curl error while the trimmed value returned 200.

        The same hazard applies to the token: a stray space would be sent in
        the Authorization header and produce a 401 at finalize, with the cause
        suppressed. ``label`` already trimmed; these two, which are the pair
        that actually break capture, did not.
        """
        if isinstance(v, str):
            return v.strip()
        # auth_token may already be a SecretStr when constructed directly
        # rather than parsed from an env var. Unwrapping and rewrapping keeps
        # both paths normalised - a test caught this asymmetry.
        if isinstance(v, SecretStr):
            return SecretStr(v.get_secret_value().strip())
        return v

    @field_validator("url")
    @classmethod
    def _reject_internal_whitespace(cls, v: str | None) -> str | None:
        """Fail loudly on whitespace INSIDE the URL - it cannot be guessed away.

        Trimming the ends is safe and unambiguous. A space in the middle is a
        genuinely malformed value, and silently mangling it further would hide
        an operator error rather than surface it.
        """
        if v is not None and any(c.isspace() for c in v):
            msg = (
                "SYN_SESSION_STORE_URL contains whitespace inside the value. "
                "Check the vault entry for a pasted line break or a stray space."
            )
            raise ValueError(msg)
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
    def display_label(self) -> str:
        """The operator's label if it is a usable identifier, otherwise empty.

        "Verbatim" in the sense that matters: the operator's own text, never a
        value derived from the URL. It does NOT mean any string reaches the log.
        A label containing a newline could forge a second posture record, and
        one built from homoglyphs or combining marks can render as a store it is
        not - and a posture line an operator cannot trust is worse than no label
        at all.

        Anything outside `_LABEL_PATTERN` yields "", the same as unset. The
        invalid text is deliberately NOT echoed: whatever it is, it is probably
        not what the operator believed they set, and echoing it is how a
        mis-pasted secret reaches the log this field exists to keep clean.
        `has_unusable_label` lets a caller report the problem without repeating
        the value.
        """
        return usable_label(self.label)

    @property
    def has_unusable_label(self) -> bool:
        """True when a label was configured but cannot be used.

        Distinguishes "none declared" from "one was declared and it is not
        usable". Both are `""` through `display_label`, but the second is a
        misconfiguration worth reporting - without repeating the value.
        """
        return bool(self.label.strip()) and not self.display_label

    @property
    def display_deployment(self) -> str:
        """The operator's deployment identity override, or "" when unset.

        "" means "no override" and callers derive the identity from
        APP_ENVIRONMENT as before. An unusable value yields "" too, so a
        malformed override degrades to the derived identity rather than
        stamping garbage onto every exported session.

        The invalid text is deliberately NOT echoed, matching `display_label`:
        whatever it is, it is probably not what the operator believed they set.
        """
        return usable_deployment(self.deployment)

    @property
    def has_unusable_deployment(self) -> bool:
        """True when a deployment override was configured but cannot be used.

        Distinguishes "none declared" from "one was declared and it is not
        usable". Worth reporting: the operator set it precisely so their
        sessions would be attributable, and silently falling back to the derived
        identity defeats the reason they set it.
        """
        return bool(self.deployment.strip()) and not self.display_deployment

    @property
    def auth_value(self) -> str:
        """The write token as a plain string, or empty when unset.

        Call this only at the point the value is handed to the container
        environment. Never log or interpolate the result anywhere else.
        """
        if self.auth_token is None:
            return ""
        return self.auth_token.get_secret_value()

    @property
    def effective_read_token(self) -> SecretStr | None:
        """The token to use for READS.

        A property rather than a caller-side ``or`` because there are two
        tokens and only one of them works for reading; picking wrongly fails
        as a retry loop rather than as an error, which is the hardest kind to
        notice.
        """
        # Compares the VALUE, not the object. A whitespace-only token strips
        # to empty but its SecretStr is still truthy, so an object-truthiness
        # check would send "   " as the bearer credential and 401 every read -
        # which is classified TRANSIENT, so it would look like a store outage
        # and retry forever rather than reporting a bad credential.
        if self.read_token is not None and self.read_token.get_secret_value().strip():
            return self.read_token
        return self.auth_token
