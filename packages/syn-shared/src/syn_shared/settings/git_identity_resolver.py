"""Git identity resolution using precedence rules.

Extracted from git_identity.py to reduce module complexity.
"""

from __future__ import annotations

import os
import subprocess

from syn_shared.settings.git_identity import GitIdentitySettings


class GitIdentityResolver:
    """Resolve git identity using precedence rules.

    Precedence:
    1. Workflow override (if provided)
    2. Environment variables (SYN_GIT_*)
    3. Local git config (development only)
    """

    def resolve(
        self,
        workflow_override: GitIdentitySettings | None = None,
    ) -> GitIdentitySettings:
        """Resolve git identity using precedence rules."""
        if workflow_override and workflow_override.is_configured:
            return workflow_override

        env_settings = GitIdentitySettings()
        if env_settings.is_configured:
            return env_settings

        if os.getenv("APP_ENVIRONMENT", "development") == "development":
            local_identity = self._from_local_git_config()
            if local_identity:
                return local_identity

        msg = (
            "Git identity not configured. Set SYN_GIT_USER_NAME and "
            "SYN_GIT_USER_EMAIL environment variables, or use workflow override."
        )
        raise ValueError(msg)

    def _from_local_git_config(self) -> GitIdentitySettings | None:
        """Read git identity from local git config (development only)."""
        try:
            name = subprocess.run(
                ["git", "config", "--get", "user.name"],
                capture_output=True,
                text=True,
                check=False,
            )
            email = subprocess.run(
                ["git", "config", "--get", "user.email"],
                capture_output=True,
                text=True,
                check=False,
            )
            if name.returncode == 0 and email.returncode == 0:
                user_name = name.stdout.strip()
                user_email = email.stdout.strip()
                if user_name and user_email:
                    return GitIdentitySettings(
                        user_name=user_name,
                        user_email=user_email,
                    )
        except FileNotFoundError:
            pass
        return None
