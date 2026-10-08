"""Every fix prompt verifies at its own unverified push instead of refusing (PC-128).

A resume of a run orphaned mid-fix is checked out at the head that run's own
fix attempt pushed, and the resumed phase is told so in the resume note under
`OWN_UNVERIFIED_PUSH`. The prompt's checkout gate is what acts on it, so this
runs each fix prompt's checkout block against a fake git, the same way the
PC-63 tests do, with the SHA the prompt's own words select as verified.

The phrase is read from the platform's constant, not retyped, so the note the
platform writes and the words the prompt keys on cannot drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.resume_handoff import (
    OWN_UNVERIFIED_PUSH,
)

pytestmark = pytest.mark.unit

_SDLC = Path(__file__).resolve().parents[2] / "workflows" / "sdlc"
_FIX_PROMPTS = sorted(
    [
        *(_SDLC / "reverify-pr" / "phases").glob("fix*.md"),
        *(_SDLC / "implement-v3" / "phases").glob("fix*.md"),
        _SDLC / "implement" / "phases" / "fix.md",
    ]
)
VERIFIED, OWN_PUSH, FOREIGN = "a" * 40, "b" * 40, "f" * 40


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _checkout_section(raw: str) -> str:
    start = raw.index("\n## Check out exactly what verification reviewed\n")
    return raw[start : raw.index("\n## ", start + 1)]


def _fix_checkout(prompt: Path, *, remote: str, note_names: str | None) -> str | None:
    """What the prompt checks out, or None where its gate says stop.

    ``note_names`` is the head the resume note marks `OWN_UNVERIFIED_PUSH`,
    when there is such a note.
    """
    checkout = _checkout_section(prompt.read_text())
    verified = VERIFIED
    if (
        note_names is not None
        and f"`{OWN_UNVERIFIED_PUSH}`" in checkout
        and "the verified SHA above is replaced by the head SHA that note names"
        in _flat(checkout)
    ):
        verified = note_names
    block = re.search(r"```\n(.*?)```", checkout, re.S)
    assert block, f"{prompt} no longer gives the checkout commands"
    head, parsed = "", []
    for line in block.group(1).splitlines():
        cmd = line.replace("<branch>", "b").replace("<verified-sha>", verified)
        if cmd == "git rev-parse origin/b":
            parsed.append(remote)
        elif cmd.startswith("git checkout -B b "):
            head = cmd.rsplit(" ", 1)[1]
        elif cmd == "git rev-parse HEAD":
            parsed.append(head)
    assert len(parsed) == 2, f"{prompt} no longer runs both rev-parse checks"
    return head if all(sha == verified for sha in parsed) else None


def test_every_fix_prompt_is_covered() -> None:
    assert len(_FIX_PROMPTS) == 7


@pytest.mark.parametrize("prompt", _FIX_PROMPTS, ids=lambda p: f"{p.parts[-3]}/{p.name}")
class TestTheFixGate:
    def test_own_unverified_commits_are_checked_out_to_reverify(self, prompt: Path) -> None:
        assert _fix_checkout(prompt, remote=OWN_PUSH, note_names=OWN_PUSH) == OWN_PUSH

    def test_the_note_requires_reverifying_before_any_change(self, prompt: Path) -> None:
        checkout = _flat(_checkout_section(prompt.read_text()))
        assert "Before you change anything, re-run the verification" in checkout

    def test_a_foreign_head_still_stops_the_phase(self, prompt: Path) -> None:
        assert _fix_checkout(prompt, remote=FOREIGN, note_names=None) is None
        # The note names the run's own head; origin holding another is a stop.
        assert _fix_checkout(prompt, remote=FOREIGN, note_names=OWN_PUSH) is None

    def test_without_a_push_nothing_changes(self, prompt: Path) -> None:
        assert _fix_checkout(prompt, remote=VERIFIED, note_names=None) == VERIFIED
