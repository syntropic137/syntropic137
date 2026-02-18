"""Accessible Repository read model.

Represents a repository that the GitHub App installation can access.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AccessibleRepository:
    """Read model for a repository accessible to the GitHub App.

    Attributes:
        id: GitHub repository ID.
        name: Repository name (without owner).
        full_name: Full repository name (owner/repo).
        private: Whether the repository is private.
        default_branch: Default branch name.
        installation_id: The installation that has access.
    """

    id: int
    name: str
    full_name: str
    private: bool
    default_branch: str
    installation_id: str

    @property
    def owner(self) -> str:
        """Get the repository owner from full_name."""
        return self.full_name.split("/")[0] if "/" in self.full_name else ""

    def clone_url(self, token: str) -> str:
        """Get the clone URL with authentication.

        Args:
            token: Installation access token.

        Returns:
            HTTPS clone URL with token for authentication.
        """
        return f"https://x-access-token:{token}@github.com/{self.full_name}.git"
