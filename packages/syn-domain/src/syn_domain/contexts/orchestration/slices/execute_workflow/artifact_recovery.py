"""Where a phase's conclusion comes from when its deliverable is not on disk.

THE FAILURE THIS EXISTS TO STOP (#1195, #1300). In `exec-0bac0e1ed2b2` a
`verify` phase ran for nine and a half minutes, 60 operations and 1.9M tokens,
and then wrote its deliverable as a zero-byte file. `CreateArtifactCommand`
refused the empty content - correctly, an empty verdict is not a verdict - and
the refusal propagated all the way out as a raw Pydantic `ValidationError`,
failing the ENTIRE execution and discarding a verdict that had already been
computed.

#1300 is the same incident one step earlier: three `implement` phases, $38.62,
finished their work - branch pushed, change correct - and wrote NO file at all.
Each run was discarded for a missing report rather than a defect. Prompting was
tried first and is not enough: `sdlc-implement-v2` names the output path in
every phase and a v2 run still finished without writing it.

The write path was treated as the only route to the phase's conclusion. It is
not: the agent said what it concluded on its own stream, and the stream
processors now hold on to that (`StreamResult.last_agent_message`). This module
is the decision to use it.

WHY ONE FUNCTION FOR BOTH. "The file was empty" and "there was no file" differ
only in what the reader must be told; the decision - is there a conclusion to
salvage, and what does the salvaged artifact look like - is identical, and
splitting it would give two places for the marker, the banner and the storable
threshold to drift apart. The caller says what it found on disk and gets back
either a whole artifact or nothing.

WHY A SEPARATE MODULE. The collector knows what was written and the stream
processor knows what was said; neither should learn the other's job, and
`ArtifactCollector` should not grow a vocabulary of banners and markers. The
caller asks one question - "can this phase's deliverable be recovered?" - and
gets back an artifact it can store as-is, down to the path it is filed under.
It never learns how the answer was reached, which is what lets the answer
change without touching the collector.

WHAT THIS IS NOT. It is not a relaxation of the empty-content rule. The rule
still lives on `CreateArtifactCommand.content` and is still enforced there;
this runs BEFORE that command is built and either produces real content or
declines, in which case the phase fails with an error saying so in operator
language. Recovery is never silent: the recovered artifact says in its own
title and first line where its content came from, because content that arrived
by a different route is a different thing from content the phase wrote, and a
reader has to be able to tell.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol

from syn_domain.contexts.artifacts import MIN_ARTIFACT_CONTENT_LENGTH

__all__ = [
    "RECOVERED_SOURCE_PATH",
    "RECOVERED_TITLE_MARKER",
    "DescribeWork",
    "RecoveredArtifact",
    "is_storable",
    "recover_deliverable",
]


class DescribeWork(Protocol):
    """Where the phase's work stands, in the words an operator reads.

    A port, deliberately: the collector must not learn what a remote, a ref or
    a starting point is, and the answer is expensive enough (it asks git) that
    it is worth asking only on the rare path that needs it. Returning None
    means nobody could look - an absent answer, never an answer of "nothing
    changed".
    """

    async def __call__(self) -> str | None: ...


#: Stamped on the title of any artifact that reached the store by recovery.
#:
#: The title is the field an operator sees in a listing and an API client gets
#: on `ArtifactDetail` without fetching content, so it is where the fact has to
#: be visible. `phases[].artifact_id` leads here from the execution detail,
#: which is the whole chain from "this phase completed" to "and this is how its
#: output was obtained".
RECOVERED_TITLE_MARKER: Final[str] = "[recovered from transcript]"

#: Where a recovery files an artifact whose phase wrote no file at all.
#:
#: A recovered artifact still has to reach the next phase, and the handoff
#: rebuilds the input tree from `source_path` (#988). Leaving it unset would
#: route this content through the flat `<phase-id>.md` alias only, which is
#: kept for one release and then goes - so the salvage would quietly stop
#: arriving. The name is deliberately not a name a phase author would choose,
#: so the tree itself says the file was reconstructed rather than written.
RECOVERED_SOURCE_PATH: Final[str] = "artifacts/output/recovered-from-transcript.md"

_PREAMBLE: Final[str] = "> **Recovered from the session transcript (issues #1195, #1300).** "

#: What the reader is told, chosen by what was actually found on disk. Both
#: end in the same sentence because the caveat is the same one: this is what
#: the agent said, not what it set out to write.
_WROTE_AN_EMPTY_FILE: Final[str] = (
    "This phase wrote `{wrote}` and the file was empty, so what follows is the "
    "last message its agent produced, not the deliverable it intended to write."
)
_WROTE_NOTHING: Final[str] = (
    "This phase declared an output artifact and wrote no collectable file "
    "under `artifacts/output/`, so what follows is the last message its agent "
    "produced, not the deliverable it owed. Its other work - commits, pushed "
    "branches - is unaffected by this and is described below if the agent "
    "described it."
)
_CAVEAT: Final[str] = (
    " It may be a complete conclusion or it may be a sign-off line; read it as "
    "evidence of what the phase decided, not as the phase's own document.\n\n"
)

#: Where the branch survived, when anyone could look.
#:
#: This is the #1200 branch report, carried into the artifact. On the FAILURE
#: path that report is appended to the error message and stored on the event,
#: which is exactly where a reader looks when a run dies. A recovered phase
#: does not die, so nothing would ever append it - and the one incident #1300
#: measured is a phase whose real output was a pushed branch. Naming it here
#: is what makes the salvage a thing the next phase can act on rather than a
#: transcript to read.
_WHERE_THE_WORK_IS: Final[str] = "\n\n---\n\n## Where this phase's work stands\n\n{work}\n"


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

    Carries all three fields because all three have to change together:
    content the reader cannot tell apart from a real deliverable is worse than
    no content, a marked title over unmarked content invites the opposite
    mistake, and a path is what decides whether the next phase ever sees it.
    """

    content: str
    title: str
    source_path: str


def recover_deliverable(
    *,
    last_agent_message: str | None,
    wrote: str | None,
    title: str,
    work: str | None = None,
) -> RecoveredArtifact | None:
    """The artifact to store in place of a deliverable that is not on disk.

    `wrote` is the path of the file the phase wrote and left empty, or None
    when it wrote no collectable file at all. It selects what the reader is
    told and where the salvage is filed; it is not a mode switch on whether
    recovery happens, because the question - "did this phase reach a
    conclusion anywhere" - is the same one in both incidents.

    `work` is where the phase's branches stand (`describe_observed_branches`),
    appended verbatim when it is known. It is a separate argument from the
    message because it is a separate kind of evidence - what git can see
    versus what the agent claimed - and a reader picking the work up needs the
    first even when the second is a sign-off line.

    None means the transcript is empty too - the agent genuinely said nothing -
    and the caller should fail the phase rather than invent a deliverable. That
    distinction is the point of the whole module: "we lost what it said" and
    "it said nothing" are different incidents and must not share an outcome.
    A `work` report alone is NOT a conclusion and does not make one: a phase
    that pushed a branch and said nothing about it still reached no verdict,
    and that failure is reported where failures are reported.
    """
    said = (last_agent_message or "").strip()
    if not said:
        return None
    reason = _WROTE_AN_EMPTY_FILE.format(wrote=wrote) if wrote is not None else _WROTE_NOTHING
    where = _WHERE_THE_WORK_IS.format(work=work) if work else ""
    return RecoveredArtifact(
        content=_PREAMBLE + reason + _CAVEAT + said + where,
        title=f"{title} {RECOVERED_TITLE_MARKER}",
        source_path=wrote if wrote is not None else RECOVERED_SOURCE_PATH,
    )
