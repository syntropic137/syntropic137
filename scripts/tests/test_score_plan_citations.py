"""The scorer must never score a citation better than reality.

Every test here pins a defect that was live in this script and that a codex
review found. They existed because the only verification was ad-hoc probes in
/tmp that vanished with the shell, while the numbers the script produced were
being published.

The direction matters and is the organising idea: **fail-toward-bad is
acceptable, fail-toward-good is not.** A scorer that under-reports makes a plan
look worse than it is, and someone investigates. A scorer that over-reports
makes a fabricated citation look checked, and nobody does.

The worst instance, and the reason this file exists: `--rev` silently fell back
to the working tree on any git error, so a NONEXISTENT revision scored 100% and
a file absent at the revision scored 100% by being read off disk instead.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from scripts.score_plan_citations import (
    Citation,
    RevisionError,
    extract,
    resolve_revision,
    strip_examples,
    verify,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _repo(tmp_path: Path) -> Path:
    """A real git repo with one committed file, and one uncommitted file.

    Uncommitted-but-present is the exact shape that made `--rev` lie: the file
    is on disk, so a working-tree fallback finds it, but it is not in the tree
    being scored against.
    """

    def run(*a: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "tracked.py").write_text("\n".join(f"line {i}" for i in range(1, 11)))
    run("add", "src/tracked.py")
    run("commit", "-qm", "one")
    (tmp_path / "src" / "untracked.py").write_text("only on disk\n")
    return tmp_path


class TestRevisionModeNeverFallsBackToTheWorkingTree:
    """The defect that invalidated a day of published numbers."""

    def test_an_unresolvable_revision_refuses_rather_than_scoring(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        with pytest.raises(RevisionError):
            verify(extract("src/tracked.py:1"), repo, "no-such-revision")

    def test_a_file_absent_at_the_revision_does_not_resolve(self, tmp_path: Path) -> None:
        """It is on disk. Reading it from there is what made this lie."""
        repo = _repo(tmp_path)
        (verdict,) = verify(extract("src/untracked.py:1"), repo, "HEAD")
        assert verdict.ok is False

    def test_the_same_citation_resolves_in_working_tree_mode(self, tmp_path: Path) -> None:
        """The negative control: the file IS there, so the two modes must
        legitimately disagree. Without this, the test above could pass for a
        reason unrelated to the revision."""
        repo = _repo(tmp_path)
        (verdict,) = verify(extract("src/untracked.py:1"), repo, None)
        assert verdict.ok is True

    def test_a_revision_resolves_to_an_immutable_oid(self, tmp_path: Path) -> None:
        """Pinned once, so a branch that moves mid-run cannot split the score
        across two trees."""
        repo = _repo(tmp_path)
        oid = resolve_revision(repo, "HEAD")
        assert len(oid) == 40
        assert oid == resolve_revision(repo, oid)


class TestMalformedCitationsAreNotCroppedIntoCleanOnes:
    """The regex matched from the middle, turning a bad citation into a good one."""

    @pytest.mark.parametrize(
        "text",
        [
            "/src/tracked.py:1",
            "bad\\src/tracked.py:1",
            "src/tracked.py:1-junk",
        ],
    )
    def test_an_invalid_form_yields_no_citation(self, text: str) -> None:
        assert extract(text) == []

    @pytest.mark.parametrize(
        "text",
        [
            "see src/tracked.py:1-10 here",
            "see `src/tracked.py:12` here",
            "(src/tracked.py:3).",
        ],
    )
    def test_ordinary_forms_still_extract(self, text: str) -> None:
        """The tightening must not silence real citations -- plans write them
        in backticks, in parentheses, and mid-sentence."""
        assert len(extract(text)) == 1


class TestRangesMustAddressSomething:
    @pytest.mark.parametrize(("line", "end"), [(10, 2), (1, 0), (0, None)])
    def test_a_backwards_or_zero_span_is_not_well_formed(self, line: int, end: int | None) -> None:
        assert Citation("src/tracked.py", line, end).well_formed is False

    def test_a_malformed_span_is_not_rendered_as_a_valid_one(self) -> None:
        """`:1-0` printed as `:1`, because 0 is falsey -- so a broken citation
        appeared well-formed in the very output used to review it."""
        assert Citation("src/tracked.py", 1, 0).label == "src/tracked.py:1-0"

    @pytest.mark.parametrize(("line", "end"), [(10, 2), (1, 0), (0, None)])
    def test_a_malformed_span_addresses_nothing_even_in_a_long_file(
        self, line: int, end: int | None
    ) -> None:
        """The property that actually matters, and the one the first version of
        this file missed: `well_formed` and `in_range` were each tested alone,
        so removing the well-formedness guard FROM `in_range` killed no test.
        A malformed citation would have scored as resolving."""
        assert Citation("src/tracked.py", line, end).in_range(1000) is False

    def test_the_end_of_a_range_is_inclusive(self) -> None:
        assert Citation("src/tracked.py", 1, 10).in_range(10) is True
        assert Citation("src/tracked.py", 1, 11).in_range(10) is False


class TestExactMeansUsableFromTheRepoRoot:
    def test_a_dot_relative_path_is_not_exact(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        (verdict,) = verify(extract("look at ./src/tracked.py:1"), repo, None)
        assert verdict.exact is False

    def test_an_escaping_path_is_not_exact(self, tmp_path: Path) -> None:
        """`../` can resolve outside the repository entirely."""
        repo = _repo(tmp_path)
        name = repo.name
        (verdict,) = verify(extract(f"look at ../{name}/src/tracked.py:1"), repo, None)
        assert verdict.exact is False

    def test_a_root_relative_path_is_exact(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        (verdict,) = verify(extract("src/tracked.py:1"), repo, None)
        assert verdict.exact is True


class TestExamplesAreNotClaims:
    def test_a_fenced_citation_is_not_counted(self) -> None:
        text = "real src/tracked.py:1\n\n```\nsrc/tracked.py:5\n```\n"
        assert [c.label for c in extract(text)] == ["src/tracked.py:1"]

    def test_inline_code_is_preserved(self) -> None:
        """The obvious version of the fence fix also stripped inline code and
        deleted EVERY real citation in every plan measured -- plans name files
        as `path/to/file.py:12`, which is ordinary markdown, not an example."""
        assert len(extract("see `src/tracked.py:7` for this")) == 1

    def test_stripping_preserves_line_count(self) -> None:
        """Blanked, not deleted, so any line-based reporting stays aligned."""
        text = "a\n```\nb\nc\n```\nd\n"
        assert len(strip_examples(text).splitlines()) == len(text.splitlines())


class TestOneLocationCountsOnce:
    def test_a_singleton_span_and_a_bare_line_are_the_same_location(self) -> None:
        """Counted twice, so a plan that varied its spelling was scored against
        a bigger denominator than one that did not."""
        assert len(extract("src/tracked.py:5 and src/tracked.py:5-5")) == 1

    def test_genuinely_different_spans_are_kept_apart(self) -> None:
        assert len(extract("src/tracked.py:5 and src/tracked.py:5-6")) == 2
