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

import re
from dataclasses import dataclass
from typing import Final, Protocol

from syn_domain.contexts.artifacts import MIN_ARTIFACT_CONTENT_LENGTH

__all__ = [
    "RECOVERED_SOURCE_PATH",
    "RECOVERED_TITLE_MARKER",
    "DescribeWork",
    "RecoveredArtifact",
    "is_storable",
    "is_usable_conclusion",
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


#: How much a salvaged message has to REPORT before it can stand in for a
#: deliverable, counted in words that survive `_reporting_words` below.
#:
#: The floor is the weakest half of the bar and is calibrated, not guessed. The
#: shortest message this repository already treats as a genuine conclusion is
#: #1195's verify verdict - "VERDICT: the implementation is sound and the gates
#: are green", ten words - and the shapes #1300's review refuses ("Done.", a
#: one-line refusal) leave nothing at all once ceremony and stance are removed.
#: Eight sits below the first and above the second, deliberately nearer the
#: permissive end: a false accept produces a title-marked, banner-wrapped
#: artifact that every reader can see arrived by transcript, while a false
#: reject discards a finished run, which is the $38.62 #1300 measured.
_MIN_CONCLUSION_WORDS: Final[int] = 8

#: Sentence, clause and line ends - what splits a message into things it says.
_SEGMENT_BOUNDARY: Final[re.Pattern[str]] = re.compile(r"[.!?;\n]+")

#: A segment that only announces that the phase finished.
#:
#: Matched on the whole normalised segment, never as a substring, so "Done."
#: is ceremony and "Done replacing the retry loop" is not.
_CEREMONY: Final[frozenset[str]] = frozenset(
    {
        "",
        "ok",
        "okay",
        "done",
        "all done",
        "complete",
        "completed",
        "task complete",
        "task completed",
        "finished",
        "all finished",
        "task finished",
        "success",
        "all set",
        "thanks",
        "thank you",
        "im done",
        "i am done",
        "ive finished",
        "i have finished",
        "ive finished the task",
        "i have finished the task",
    }
)

#: A segment is a STANCE when it says what the agent would or could do.
_STANCE: Final[re.Pattern[str]] = re.compile(
    r"\b(refus\w*|decline[ds]?|declining|will not|wont|cannot|can not|cant|"
    r"could not|couldnt|unable to|not going to|not permitted to|not allowed to)\b"
)

#: What turns a stance back into a report: the reason behind it.
_GIVES_A_REASON: Final[re.Pattern[str]] = re.compile(
    r"\b(because|since|due to|owing to|as the|as it|the reason|without which)\b"
)

_NOT_WORDS: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9 ]+")


def _reporting_words(message: str) -> int:
    """How many words of `message` say something about the phase's work.

    Ceremony and bare stance are both excluded, for the same reason: neither
    tells the next phase anything it can act on. "Done." announces only that
    the message has ended, and "I refuse to modify production auth code
    without explicit sign-off" announces only where the agent stood - a
    downstream phase reading either as its input has a report in name and
    nothing in hand.

    A stance WITH its reasons is not excluded, and that asymmetry is the point.
    "I could not push the branch because the credential rejects workflow
    changes" is a finding: it says what was attempted, what stopped it, and
    what a human has to change. Refusals are first-class deliverables in this
    system; unexplained ones are not deliverables at all.

    Exclusion is per segment, never whole-message, so one "I could not" inside
    a long report costs that clause and nothing else.
    """
    words = 0
    for segment in _SEGMENT_BOUNDARY.split(message):
        normalised = _NOT_WORDS.sub("", segment.lower().replace("'", "")).strip()
        normalised = " ".join(normalised.split())
        if normalised in _CEREMONY:
            continue
        if _STANCE.search(normalised) and not _GIVES_A_REASON.search(normalised):
            continue
        words += len(normalised.split())
    return words


def is_usable_conclusion(message: str) -> bool:
    """Whether `message` is a conclusion a downstream phase can act on.

    THE QUESTION THIS ANSWERS, and why it is not "is this non-empty". The
    salvage stores what the agent said as the phase's deliverable, and the next
    phase reads that artifact as its INPUT and acts on it. A stored artifact
    reading "Done." therefore does something strictly worse than the failure it
    replaced: the run advances, the next phase believes it has been handed a
    report, and it builds on nothing. Salvage is for rescuing work that was
    done, not for laundering a phase that did none.

    WHAT WAS CHOSEN. A message is usable when at least
    `_MIN_CONCLUSION_WORDS` of it REPORT - words left after dropping the
    segments that announce completion and the segments that state a position
    without a reason for it. Length alone would not do: the genuine verdict
    #1195 rescues and the bare refusal #1300 refuses are both ten words, so
    any floor that keeps the first admits the second. What separates them is
    not size but subject - one is about the work, the other is about the
    agent - and that is what is measured here.

    WHAT IT CANNOT DO. It cannot tell a true report from a plausible-sounding
    false one; nothing static can. It is a floor on substance, not a check on
    honesty, and the artifact stays marked as recovered precisely because that
    remains the reader's job.
    """
    return _reporting_words(message) >= _MIN_CONCLUSION_WORDS


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

    None means there is no conclusion to salvage - the agent said nothing, or
    said nothing a downstream phase could act on (`is_usable_conclusion`) - and
    the caller should fail the phase rather than invent a deliverable. That
    distinction is the point of the whole module: "we lost what it said" and
    "it said nothing worth having" are different incidents from "it reported",
    and must not share an outcome with it.
    A `work` report alone is NOT a conclusion and does not make one: a phase
    that pushed a branch and said nothing about it still reached no verdict,
    and that failure is reported where failures are reported.
    """
    said = (last_agent_message or "").strip()
    if not is_usable_conclusion(said):
        return None
    reason = _WROTE_AN_EMPTY_FILE.format(wrote=wrote) if wrote is not None else _WROTE_NOTHING
    where = _WHERE_THE_WORK_IS.format(work=work) if work else ""
    return RecoveredArtifact(
        content=_PREAMBLE + reason + _CAVEAT + said + where,
        title=f"{title} {RECOVERED_TITLE_MARKER}",
        source_path=wrote if wrote is not None else RECOVERED_SOURCE_PATH,
    )
