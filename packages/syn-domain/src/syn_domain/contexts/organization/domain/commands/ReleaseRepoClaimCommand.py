"""Release Repo Claim command.

Command to release a repo claim, allowing the name to be re-registered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class ReleaseRepoClaimCommand:
    """Command to release a repository claim.

    Attributes:
        claim_id: Deterministic claim ID to release.
        repo_id: ID of the repo being deregistered.
        command_id: Unique identifier for this command.
    """

    claim_id: str
    repo_id: str
    command_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.claim_id:
            raise ValueError("claim_id is required")
        if not self.repo_id:
            raise ValueError("repo_id is required")
