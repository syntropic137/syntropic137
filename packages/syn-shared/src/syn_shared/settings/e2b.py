"""E2B remote workspace backend configuration (#1915). Off by default.

E2B support ships dark: with ``SYN_E2B_ENABLED`` unset nothing here is read
by the workspace wiring, and workspaces run on Docker exactly as before.
Turned on, the configuration must be complete or the settings refuse to
load, so a process that asked for E2B never starts on Docker instead.

The API key is a ``SecretStr``: it is unwrapped only where the E2B client is
constructed, and never logged or written into an event.
"""

from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class E2BSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SYN_E2B_",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
        env_ignore_empty=True,
        frozen=True,
    )

    enabled: bool = Field(
        default=False,
        description=(
            "Run workspaces as E2B cloud sandboxes instead of Docker containers. "
            "Requires SYN_E2B_API_KEY and SYN_E2B_TEMPLATE; startup fails without them. "
            "Experimental: agent launches are not supported on E2B yet (#1915)."
        ),
    )
    api_key: SecretStr | None = Field(
        default=None,
        description=(
            "E2B API key. From the operator's environment or keychain; never commit it. "
            "Rotating it changes the E2B executor's reap scope (a digest of the key): rotate "
            "only with no live E2B runs, and set the same new key as SYN_E2B_RECOVERY_API_KEY "
            "on every executor holding a Recovery Kit in the same step."
        ),
    )
    template: str = Field(
        default="",
        max_length=256,
        description=(
            "E2B template id or name every sandbox starts from, built from the pinned "
            "workspace image with agentic-workspace's build_template."
        ),
    )
    cpu_count: int = Field(
        default=2,
        ge=1,
        le=64,
        description=(
            "vCPUs the template was built with. A workspace asking for more is refused, "
            "since E2B sizes a sandbox by its template, not per sandbox."
        ),
    )
    memory_mb: int = Field(
        default=2048,
        ge=512,
        le=262144,
        description=(
            "Memory (MB) the template was built with. A workspace asking for more is refused."
        ),
    )
    timeout_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Sandbox lifetime: E2B kills a sandbox this long after it was created.",
    )

    breaker_failures: int = Field(
        default=3,
        ge=1,
        le=100,
        description=(
            "Outage Breaker (#1917): consecutive failed sandbox creates after which this "
            "E2B executor stops claiming runs for SYN_E2B_BREAKER_COOLDOWN_S. Capacity and "
            "runs already held are untouched. Read only with the Run Queue on."
        ),
    )
    breaker_cooldown_s: int = Field(
        default=300,
        ge=1,
        le=86400,
        description=(
            "Seconds an E2B executor's claims stay disabled once the Outage Breaker trips. "
            "After it, one claim is tried: a failed create disables claims again at once, "
            "a successful one clears the count."
        ),
    )
    recovery_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Recovery Kit (#1917): an E2B API key this executor holds only to clean up after "
            "a dead E2B executor (list, attach with ownership check, kill), never to create. "
            "Set it on a local executor to let it reconcile E2B runs. It must be the key the "
            "E2B executor uses: the reap scope is derived from the key. Unset: this executor "
            "never fences an E2B run. When SYN_E2B_API_KEY is rotated, change this in the "
            "same step, with no live E2B runs."
        ),
    )

    @model_validator(mode="after")
    def _complete_when_enabled(self) -> Self:
        if not self.enabled:
            return self
        missing = [
            name
            for name, present in (
                ("SYN_E2B_API_KEY", self.api_key is not None),
                ("SYN_E2B_TEMPLATE", bool(self.template)),
            )
            if not present
        ]
        if missing:
            msg = (
                f"SYN_E2B_ENABLED is true but {' and '.join(missing)} is unset. "
                "E2B workspaces cannot start without them, and Syn137 does not fall "
                "back to Docker when E2B was asked for. Set them, or unset SYN_E2B_ENABLED."
            )
            raise ValueError(msg)  # pydantic reports it as a ValidationError
        return self
