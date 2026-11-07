"""Contributor guard: decides whether a webhook's contributor may fire triggers (#580).

The guard is system-wide and runs before any per-trigger condition, so an
operator protects every trigger with one setting instead of repeating
``sender.login`` conditions on each rule. ADR-040-github-trigger-architecture anticipated it as the
"contributor allowlist" guard; a refusal is recorded as a
``TriggerBlockedEvent`` like every other guard.

Who is judged is the *contributor*: the author of the content the event is
about, not the sender. A ``pull_request.synchronize`` is about the PR author's
code even when a maintainer pushed it, and a ``check_run`` is sent by CI on
behalf of whoever wrote the commits. GitHub reports trust as
``author_association`` on that content (comment, review, pull request or
issue). The most specific content with an author decides: a review's author
is judged on the review's own ``author_association``, never on the pull request
around it, and a review the Events API delivers without one is untrusted unless
its author's login is allowed. Content whose author is ``null`` (a deleted
account) is judged as nobody, never as its parent or sender. Events that carry
no such content (``check_run``, ``push``) are judged on their sender, which for
CI events is a bot, or for a polled event on the Events API ``actor``.

Bots get no blanket pass. ``github-actions[bot]`` sends the ``check_run`` for
an external contributor's PR, so exempting bots would let exactly the event
this guard exists to stop straight through. A bot fires under a restrictive
mode only when its login is listed in ``allowed_logins``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from syn_domain.contexts.github._shared.trigger_evaluation_types import EVENTS_API_ACTOR_KEY

CONTRIBUTOR_GUARD_NAME = "contributor_guard"

TRUSTED_ASSOCIATIONS: frozenset[str] = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
"""``author_association`` values that count as a trusted contributor."""


class ContributorGuardMode(StrEnum):
    """Which contributors may make a trigger fire."""

    ALLOW_ALL = "allow_all"
    """Every contributor. The default, and the behaviour before #580."""

    TRUSTED = "trusted"
    """Contributors whose ``author_association`` is OWNER, MEMBER or
    COLLABORATOR, plus any login in ``allowed_logins``."""

    ALLOWLIST = "allowlist"
    """Only logins in ``allowed_logins``."""


@dataclass(frozen=True)
class Contributor:
    """Who an event is attributed to, as far as the payload says."""

    login: str
    association: str | None
    """``author_association`` of the content, or None when the payload has none."""


@dataclass(frozen=True)
class ContributorPolicy:
    """The operator's contributor rule. ``refusal()`` is the whole decision."""

    mode: ContributorGuardMode = ContributorGuardMode.ALLOW_ALL
    allowed_logins: frozenset[str] = frozenset()
    """Logins that may always fire. Compared case-insensitively, as GitHub does."""

    def refusal(self, payload: object) -> str | None:
        """Return why the payload's contributor may not fire, or None if they may.

        ``payload`` is the raw webhook body; it is parsed here, once.
        """
        if self.mode is ContributorGuardMode.ALLOW_ALL:
            return None
        contributor = contributor_of(payload)
        if contributor.login.lower() in {login.lower() for login in self.allowed_logins}:
            return None
        if self.mode is ContributorGuardMode.TRUSTED:
            if contributor.association in TRUSTED_ASSOCIATIONS:
                return None
            return (
                f"Contributor {contributor.login or '<unknown>'} is not trusted "
                f"(author_association={contributor.association or 'absent'}, "
                f"mode={self.mode.value})"
            )
        return (
            f"Contributor {contributor.login or '<unknown>'} is not in the allowlist "
            f"(mode={self.mode.value})"
        )


class _User(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    login: str = ""


class _Content(BaseModel):
    """A comment, review, pull request or issue: anything with an author."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    user: _User | None = None
    author_association: str | None = None

    @property
    def declares_author(self) -> bool:
        """Whether the payload says who wrote this content, even as ``null``.

        A webhook comment or review by a deleted account carries ``"user":
        null``; the Events API trims a pull request it only refers to down to
        ``number``, ``head`` and ``base`` with no ``user`` key at all. Only the
        first is authored content with an unknown author.
        """
        return bool({"user", "author_association"} & self.model_fields_set)


class _AttributablePayload(BaseModel):
    """The slice of a GitHub webhook payload that says who it came from."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    comment: _Content | None = None
    review: _Content | None = None
    pull_request: _Content | None = None
    issue: _Content | None = None
    sender: _User | None = None
    events_api_actor: _User | None = Field(default=None, alias=EVENTS_API_ACTOR_KEY)


def contributor_of(payload: object) -> Contributor:
    """Attribute a payload to its content's author, else its sender, else its actor.

    A payload that does not parse is attributed to nobody, which every
    restrictive mode refuses.
    """
    try:
        parsed = _AttributablePayload.model_validate(payload)
    except ValidationError:
        return Contributor(login="", association=None)
    # Most specific first: on an issue_comment the comment is what the event is
    # about, and the issue around it is context. The first content that declares
    # an author decides, association or not, so an unclassified comment or
    # review never borrows the trust of the PR or issue it sits on, and one whose
    # author is null is judged as nobody rather than as its parent or sender.
    for content in (parsed.comment, parsed.review, parsed.pull_request, parsed.issue):
        if content is not None and content.declares_author:
            login = content.user.login if content.user is not None else ""
            return Contributor(login=login, association=content.author_association)
    for user in (parsed.sender, parsed.events_api_actor):
        if user is not None and user.login:
            return Contributor(login=user.login, association=None)
    return Contributor(login="", association=None)
