"""E2B remote workspace backend configuration (#1915). Off by default.

E2B support ships dark: with ``SYN_E2B_ENABLED`` unset nothing here is read
by the workspace wiring, and workspaces run on Docker exactly as before.
Turned on, the configuration must be complete or the settings refuse to
load, so a process that asked for E2B never starts on Docker instead.

The API key is a ``SecretStr``: it is unwrapped only where the E2B client is
constructed, and never logged or written into an event.

``SYN_E2B_NESTED_DOCKER`` says the template runs a Docker daemon (built with
agentic-workspace's ``DockerEngine``, AW#91). The floor below is that engine's
own, so a template too small for Docker refuses to load rather than failing
inside a run; a test in syn-adapters holds the two equal.
"""

from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: agentic-workspace ``DockerEngine.min_cpu_count``: the smallest sandbox Docker runs in.
NESTED_DOCKER_MIN_CPU_COUNT = 2
#: agentic-workspace ``DockerEngine.min_memory_mb``.
NESTED_DOCKER_MIN_MEMORY_MB = 4096


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
        description=("E2B API key. From the operator's environment or keychain; never commit it."),
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
    nested_docker: bool = Field(
        default=False,
        description=(
            "The template runs a Docker daemon (built by `just e2b-template-build`). Every "
            "sandbox then waits for `docker info` before use and advertises nested_docker. "
            "Needs SYN_E2B_CPU_COUNT>=2 and SYN_E2B_MEMORY_MB>=4096, and SYN_E2B_TEMPLATE "
            "must be the name derived from the current pins, or startup is refused."
        ),
    )
    docker_ready_seconds: float = Field(
        default=30.0,
        gt=0,
        le=600,
        description=(
            "With SYN_E2B_NESTED_DOCKER: how long a new sandbox may take for `docker info` "
            "to answer before its creation fails."
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

    @model_validator(mode="after")
    def _nested_docker_fits_the_floor(self) -> Self:
        if not self.nested_docker:
            return self
        if (
            self.cpu_count < NESTED_DOCKER_MIN_CPU_COUNT
            or self.memory_mb < NESTED_DOCKER_MIN_MEMORY_MB
        ):
            msg = (
                "SYN_E2B_NESTED_DOCKER is true but the template is "
                f"{self.cpu_count} vCPU / {self.memory_mb} MB; nested Docker needs at least "
                f"{NESTED_DOCKER_MIN_CPU_COUNT} vCPU and {NESTED_DOCKER_MIN_MEMORY_MB} MB. "
                "Set SYN_E2B_CPU_COUNT and SYN_E2B_MEMORY_MB to what the template was built "
                "with, or unset SYN_E2B_NESTED_DOCKER."
            )
            raise ValueError(msg)  # pydantic reports it as a ValidationError
        return self
