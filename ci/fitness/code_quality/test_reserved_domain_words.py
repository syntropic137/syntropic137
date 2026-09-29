"""Words the orchestration context has deliberately NOT assigned a meaning.

A vocabulary is only load-bearing if reintroducing a retired word is harder
than not reintroducing it. `fork` was renamed to `resume` on 2026-09-29 and
reserved for a DIFFERENT operation that does not exist yet: starting a new run
from an arbitrary point of a COMPLETED execution, the way a git branch is taken
from a commit. If `fork` drifts back in meaning "resume", the two can never be
told apart again, and the rename would have to be done twice.

This gate is narrow on purpose. It does not ban the word everywhere: process
forks, git forks and GitHub's own `ForkEvent` are all legitimate and unrelated.
It bans it in the orchestration domain and on the execution API and CLI
surfaces, which is exactly where the collision would happen.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: Where the collision would happen. Each is a directory whose subject is the
#: execution lifecycle, so `fork` there can only mean the retired concept.
_GUARDED = (
    "packages/syn-domain/src/syn_domain/contexts/orchestration",
    "apps/syn-api/src/syn_api/routes/executions",
)

#: Files inside a guarded tree whose `fork` is demonstrably something else.
_ALLOWED = {
    # The discriminator's whole job is reading pre-rename `ExecutionForked`.
    "packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/legacy_event_shapes.py",
    "packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_legacy_event_shapes.py",
    # Drive a stored pre-rename event through the two real replay paths (#1471).
    "packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_replay_reaches_the_guard.py",
    "packages/syn-domain/src/syn_domain/contexts/orchestration/slices/start_resume/test_the_todo_list_has_the_same_gate.py",
}

#: SPAN-scoped exemptions: each is deleted from the line before the line is
#: searched, so an execution-fork word elsewhere on the same line is still
#: caught. Line-scoping would have made any line holding one of these a blind
#: spot, which is the same weakness as exempting a whole file.
#:
#: All three name a PROCESS fork under uvloop, which has nothing to do with
#: this vocabulary.
_PROCESS_FORK_SPANS = ("GRPC_ENABLE_FORK_SUPPORT", "grpc fork", "fork()")

#: The retired name itself, which the compatibility path must be able to say.
#: A stored `ExecutionForked` still has to be read, so the code that reads it
#: names it - and only these exact identifiers, so "fork" in any other form is
#: still caught. This is the whole legacy surface; it should never grow.
_LEGACY_NAME_SPANS = (
    "ExecutionForked",
    "_EXECUTION_FORKED",
    "on_execution_forked",
    "upcast_forked_payload",
    "read_admitted_forked_resume",
    "fork_execution_id",
    "forked_at",
    "pre-rename `ExecutionForked`",
)

_ALLOWED_SPANS = _PROCESS_FORK_SPANS + _LEGACY_NAME_SPANS

_FORK = re.compile(r"fork", re.IGNORECASE)


def _without_exempt_spans(line: str) -> str:
    """`line` with each exempt span removed, so only the rest is searched."""
    for span in _ALLOWED_SPANS:
        line = line.replace(span, "")
    return line


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "packages").is_dir():
            return parent
    msg = f"No repo root above {here}"
    raise AssertionError(msg)


def _guarded_files() -> list[Path]:
    root = _repo_root()
    found: list[Path] = []
    for tree in _GUARDED:
        base = root / tree
        assert base.is_dir(), f"{tree} does not exist; this gate guards nothing"
        found.extend(p for p in base.rglob("*.py") if p.is_file())
    return sorted(found)


def test_the_gate_has_files_to_guard() -> None:
    """A gate that scans nothing passes for the wrong reason."""
    assert len(_guarded_files()) >= 50, len(_guarded_files())


def test_every_file_exemption_still_exists() -> None:
    """A stale exemption is a hole nobody can see.

    The two exempt files exist to READ the retired name, so every `fork` in
    them is that name by construction. If either is renamed or deleted, the
    exemption must go with it rather than sitting there covering nothing.
    """
    root = _repo_root()
    missing = [path for path in _ALLOWED if not (root / path).is_file()]
    assert not missing, f"exemptions name files that no longer exist: {missing}"


def test_an_exempt_span_does_not_exempt_the_rest_of_its_line() -> None:
    """The property that makes these spans and not lines.

    Asserted on the helper directly because no such line exists in the repo
    today - and a rule only tested by the absence of violations is a rule that
    has never been tested at all.
    """
    line = "# GRPC_ENABLE_FORK_SUPPORT is unrelated, but fork_this_execution is not"

    assert _FORK.search(_without_exempt_spans(line)) is not None


def test_an_exempt_span_alone_is_exempt() -> None:
    """The control for the test above: the span itself must still pass."""
    assert _FORK.search(_without_exempt_spans("# GRPC_ENABLE_FORK_SUPPORT=false")) is None


def test_fork_stays_reserved_in_the_orchestration_domain() -> None:
    root = _repo_root()
    offenders: list[str] = []
    for path in _guarded_files():
        rel = path.relative_to(root).as_posix()
        if rel in _ALLOWED:
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if _FORK.search(_without_exempt_spans(line)):
                offenders.append(f"{rel}:{number}: {line.strip()}")

    assert not offenders, (
        "`fork` is a RESERVED word in the orchestration context: it names an "
        "operation that starts a new run from a point of a COMPLETED execution, "
        "which is not built. Resuming an unfinished execution is `resume`. "
        "See docs/architecture/orchestration-ubiquitous-language.md and "
        "ADR-014 section 7.\n" + "\n".join(offenders)
    )


def test_the_reserved_word_is_documented_as_reserved() -> None:
    """The ban must be explained where a reader looks, not only where it fires."""
    vocabulary = (
        _repo_root() / "docs/architecture/orchestration-ubiquitous-language.md"
    ).read_text()
    assert "Fork" in vocabulary, "the vocabulary must name the reserved word"
    assert "Not implemented" in vocabulary or "not implemented" in vocabulary, (
        "the vocabulary must say Fork is reserved and unbuilt, not merely mention it"
    )
