"""Contributor guard settings: who may make a trigger fire (#580).

See docs/deployment/github-app-security.md and ADR-040. The guard itself lives
in the github context (``evaluate_webhook/contributor_guard.py``); this class
only carries the operator's choice to it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TriggerContributorSettings(BaseSettings):
    """Which GitHub contributors may make a trigger spawn an agent run.

    The default, ``allow_all``, keeps every trigger firing for every
    contributor. On a public repository that lets an external contributor's PR
    start an agent run on their code with this deployment's credentials, so
    set ``trusted`` or ``allowlist`` there.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_TRIGGER_CONTRIBUTOR_",
        env_file=".env",
        extra="ignore",
    )

    mode: Literal["allow_all", "trusted", "allowlist"] = Field(
        default="allow_all",
        description=(
            "Who may make a trigger fire. allow_all: everyone (default). "
            "trusted: content authors whose GitHub author_association is OWNER, "
            "MEMBER or COLLABORATOR, plus SYN_TRIGGER_CONTRIBUTOR_ALLOWED_LOGINS. "
            "allowlist: only SYN_TRIGGER_CONTRIBUTOR_ALLOWED_LOGINS. Bots get no "
            "blanket pass under trusted or allowlist: list a bot's login to let it fire."
        ),
    )

    allowed_logins: str = Field(
        default="",
        description=(
            "Comma-separated GitHub logins that may always fire triggers, e.g. "
            "'alice,syn-engineer[bot]'. Ignored under allow_all. Do not list "
            "github-actions[bot]: it sends check_run events for external PRs too."
        ),
    )

    @property
    def allowed_login_set(self) -> frozenset[str]:
        """``allowed_logins`` parsed into individual logins."""
        return frozenset(login.strip() for login in self.allowed_logins.split(",") if login.strip())

    @model_validator(mode="after")
    def _allowlist_needs_logins(self) -> TriggerContributorSettings:
        if self.mode == "allowlist" and not self.allowed_login_set:
            raise ValueError(
                "SYN_TRIGGER_CONTRIBUTOR_MODE=allowlist with no "
                "SYN_TRIGGER_CONTRIBUTOR_ALLOWED_LOGINS would refuse every trigger; "
                "list at least one login"
            )
        return self
