"""Where a phase's conclusion comes from when the file it wrote was empty.

THE FAILURE THIS EXISTS TO STOP (#1195). In `exec-0bac0e1ed2b2` a `verify`
phase ran for nine and a half minutes, 60 operations and 1.9M tokens, and then
wrote its deliverable as a zero-byte file. `CreateArtifactCommand` refused the
empty content - correctly, an empty verdict is not a verdict - and the refusal
propagated all the way out as a raw Pydantic `ValidationError`, failing the
ENTIRE execution and discarding a verdict that had already been computed.

The write path was treated as the only route to the phase's conclusion. It is
not: the agent said what it concluded on its own stream, and the stream
processors now hold on to that (`StreamResult.last_agent_message`). This module
is the decision to use it.

WHY A SEPARATE MODULE. The collector knows what was written and the stream
processor knows what was said; neither should learn the other's job, and
`ArtifactCollector` should not grow a vocabulary of banners and markers. The
caller asks one question - "can this empty artifact be recovered?" - and gets
back either a whole artifact or nothing. It never learns how the answer was
reached, which is what lets the answer change without touching the collector.

WHAT THIS IS NOT. It is not a relaxation of the empty-content rule. The rule
still lives on `CreateArtifactCommand.content` and is still enforced there;
this runs BEFORE that command is built and either produces real content or
declines, in which case the phase fails with `EmptyPhaseArtifactError` saying
so in operator language. Recovery is never silent: the recovered artifact says
in its own title and first line where its content came from, because content
that arrived by a different route is a different thing from content the phase
wrote, and a reader has to be able to tell.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from syn_domain.contexts.artifacts import MIN_ARTIFACT_CONTENT_LENGTH

__all__ = [
    "RECOVERED_TITLE_MARKER",
    "RecoveredArtifact",
    "is_storable",
    "recover_empty_artifact",
]

#: Stamped on the title of any artifact that reached the store by recovery.
#:
#: The title is the field an operator sees in a listing and an API client gets
#: on `ArtifactDetail` without fetching content, so it is where the fact has to
#: be visible. `phases[].artifact_id` leads here from the execution detail,
#: which is the whole chain from "this phase completed" to "and this is how its
#: output was obtained".
RECOVERED_TITLE_MARKER: Final[str] = "[recovered from transcript]"

_BANNER: Final[str] = (
    "> **Recovered from the session transcript (issue #1195).** This phase "
    "wrote `{source_path}` and the file was empty, so what follows is the last "
    "message its agent produced, not the deliverable it intended to write. It "
    "may be a complete conclusion or it may be a sign-off line; read it as "
    "evidence of what the phase decided, not as the phase's own document.\n\n"
)


def is_storable(content: str) -> bool:
    """Whether the artifact store will accept `content` as it stands.

    Asks the store's own rule rather than restating it: the threshold is
    `CreateArtifactCommand.content`'s `min_length`, imported rather than
    re-typed. A second, independent spelling of "empty" here would drift from
    the constraint it exists to anticipate, and the drift would be silent -
    recovery would simply stop firing for the case it was built to catch.
    """
    return len(content) >= MIN_ARTIFACT_CONTENT_LENGTH


@dataclass(frozen=True)
class RecoveredArtifact:
    """An artifact whose content came from what the agent SAID, not what it wrote.

    Carries both fields because both have to change together: content the
    reader cannot tell apart from a real deliverable is worse than no content,
    and a marked title over unmarked content invites the opposite mistake.
    """

    content: str
    title: str


def recover_empty_artifact(
    *,
    last_agent_message: str | None,
    source_path: str,
    title: str,
) -> RecoveredArtifact | None:
    """The artifact to store instead of an empty one, or None if there is none.

    None means the transcript is empty too - the agent genuinely said nothing -
    and the caller should fail the phase rather than invent a deliverable. That
    distinction is the point of the whole module: "we lost what it said" and
    "it said nothing" are different incidents and must not share an outcome.
    """
    said = (last_agent_message or "").strip()
    if not said:
        return None
    return RecoveredArtifact(
        content=_BANNER.format(source_path=source_path) + said,
        title=f"{title} {RECOVERED_TITLE_MARKER}",
    )
