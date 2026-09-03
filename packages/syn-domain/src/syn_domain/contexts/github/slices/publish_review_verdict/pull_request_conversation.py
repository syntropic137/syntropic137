"""Port: the comment conversation on a pull request (#1097).

The domain knows a verdict must reach the pull request it judged. It does not
know that GitHub calls that an issue comment, that listing them is paginated,
or which installation token authorises the write. Those are adapter concerns.
"""

from __future__ import annotations

from typing import Protocol


class PullRequestConversation(Protocol):
    """Port: read and write the comment thread of one pull request.

    Implemented by ``syn_adapters.github.pr_conversation`` over the GitHub
    App client. Tests substitute a double.
    """

    async def head_sha(self, repository: str, pr_number: int) -> str:
        """Return the current head commit SHA of the pull request.

        Args:
            repository: Full repository name, e.g. ``"owner/repo"``.
            pr_number: Pull request number.
        """
        ...

    async def comment_bodies(self, repository: str, pr_number: int) -> list[str]:
        """Return the bodies of every comment on the pull request, oldest first."""
        ...

    async def post_comment(self, repository: str, pr_number: int, body: str) -> None:
        """Append a comment to the pull request."""
        ...
