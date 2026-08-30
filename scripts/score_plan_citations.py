"""Score a plan by whether its code citations are REAL.

WHY THIS EXISTS. Comparing workflows, models or harnesses needs a quality
signal that is not another model's opinion. "Which plan reads better" cannot be
run in CI and cannot be compared across weeks.

A plan's `file:line` citations can be checked mechanically, and they measure the
thing that actually matters: whether the plan is grounded in the codebase or
invented. A confident plan built on a citation that does not exist is the
expensive failure mode - it LOOKS verified, which is precisely why nobody
re-checks it.

This is a floor, not a ceiling. A plan can cite perfectly and still be a bad
plan. But a plan that cites badly is reliably bad, and that is worth measuring
automatically.

Usage:
    uv run python scripts/score_plan_citations.py <plan.md> [--repo <root>]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

#: `path/to/file.py:123` or `path/to/file.py:123-140`.
#:
#: Requires BOTH a directory component and a known suffix, so prose like
#: "a 3:1 ratio" is not read as a citation. Verified: that string does not match.
#:
#: KNOWN BLIND SPOT: extension-less files (`justfile`, `Dockerfile`, `Makefile`)
#: and bare filenames are invisible to this, so a citation to one is neither
#: credited nor penalised. Loosening the pattern to catch them re-admits the
#: false positives, and a scorer that counts prose as a broken citation is worse
#: than one that misses a few real ones - it would penalise good plans. Stated
#: here so the score is read as "of the citations we can check", not "of all
#: claims made".
_CITATION = re.compile(
    r"(?P<path>(?:[\w.\-]+/)+[\w.\-]+\.(?:py|ts|tsx|js|yaml|yml|toml|md|rs|sh))"
    r":(?P<line>\d+)(?:-(?P<end>\d+))?"
)


@dataclass(frozen=True)
class Citation:
    path: str
    line: int
    end: int | None

    @property
    def label(self) -> str:
        return f"{self.path}:{self.line}" + (f"-{self.end}" if self.end else "")


@dataclass(frozen=True)
class Verdict:
    citation: Citation
    file_exists: bool
    line_exists: bool
    exact: bool = True

    @property
    def ok(self) -> bool:
        return self.file_exists and self.line_exists

    #: True when the path matched several files and identified none of them.
    ambiguous: bool = False

    @property
    def reason(self) -> str:
        if not self.file_exists:
            return (
                "ambiguous - matches several files, identifies none"
                if self.ambiguous
                else "no such file anywhere in the repo"
            )
        if not self.line_exists:
            return "line is past end of file"
        if not self.exact:
            return "real file, but the path is abbreviated"
        return "ok"


def extract(text: str) -> list[Citation]:
    """Every distinct file:line citation, in order of first appearance."""
    seen: dict[str, Citation] = {}
    for m in _CITATION.finditer(text):
        c = Citation(m["path"], int(m["line"]), int(m["end"]) if m["end"] else None)
        seen.setdefault(c.label, c)
    return list(seen.values())


def _line_count_at_rev(repo: Path, rev: str, cited: str) -> int | None:
    """Line count of a path AT a revision, without touching the working tree."""
    import subprocess

    r = subprocess.run(
        ["git", "-C", str(repo), "show", f"{rev}:{cited}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return None if r.returncode != 0 else r.stdout.count("\n")


def _resolve(repo: Path, cited: str) -> tuple[Path | None, bool]:
    """Find the file a citation refers to, and whether the path was exact.

    TWO DIFFERENT QUALITIES were conflated before this: whether a plan is
    GROUNDED (the file exists) and whether its citations are USABLE (the path
    resolves as written). Scoring only exact matches reported 0% for a plan
    whose every citation pointed at a real file - measuring formatting while
    claiming to measure grounding.

    They are both worth knowing and they are not the same. A plan citing a
    fabricated file is untrustworthy; a plan citing a real file by its last two
    segments is merely inconvenient.
    """
    exact = repo / cited
    if exact.is_file():
        return exact, True
    # Abbreviated: match on a trailing path segment sequence, which is what a
    # human does when they read `routes/artifacts.py` and go looking.
    suffix = "/" + cited
    matches = [
        f
        for f in repo.rglob("*" + Path(cited).name)
        if f.is_file()
        and str(f).endswith(suffix)
        and ".venv" not in f.parts
        and ".git" not in f.parts
        and "_worktrees" not in str(f)
        and ".claude" not in f.parts
    ]
    if len(matches) == 1:
        return matches[0], False
    # AMBIGUOUS is not ABSENT, and reporting them the same way was a bug in
    # this scorer: `_shared/value_objects.py` matches four bounded contexts, so
    # the citation identifies no particular file. Still a legitimate ding - a
    # reader cannot follow it either - but "no such file" was a lie about a
    # path whose target exists several times over.
    return (None, False) if not matches else (None, True)


def verify(citations: list[Citation], repo: Path, rev: str | None = None) -> list[Verdict]:
    out: list[Verdict] = []
    for c in citations:
        target, ambiguous = _resolve(repo, c.path)
        exists = target is not None
        exact = exists and target == (repo / c.path)
        line_ok = False
        if rev is not None:
            # Authoritative when given: reads the blob at that revision rather
            # than whatever the checkout happens to hold.
            total = _line_count_at_rev(repo, rev, c.path)
            if total is not None:
                exists = True
                exact = True
                line_ok = 1 <= c.line <= total and (c.end is None or c.end <= total)
                out.append(Verdict(c, exists, line_ok, exact, False))
                continue
        if target is not None:
            try:
                # Count lines without loading the whole file into memory.
                with target.open("rb") as fh:
                    total = sum(1 for _ in fh)
                line_ok = 1 <= c.line <= total and (c.end is None or c.end <= total)
            except OSError:
                line_ok = False
        out.append(Verdict(c, exists, line_ok, bool(exact), ambiguous))
    return out


def _describe_tree(repo: Path, rev: str | None) -> str:
    """What the caller is actually being scored against, stated plainly."""
    import subprocess

    def _git(*a: str) -> str:
        r = subprocess.run(
            ["git", "-C", str(repo), *a], capture_output=True, text=True, check=False
        )
        return r.stdout.strip() if r.returncode == 0 else "?"

    if rev:
        return f"{repo} @ {rev} ({_git('rev-parse', '--short', rev)})"

    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    head = _git("rev-parse", "--short", "HEAD")
    behind = _git("rev-list", "--count", "HEAD..origin/main")
    warn = ""
    if behind.isdigit() and int(behind) > 0:
        warn = f"  ** {behind} COMMITS BEHIND origin/main - citations may read as out of range **"
    return f"{repo} @ {branch} ({head}){warn}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", type=Path)
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument(
        "--rev",
        default=None,
        help=(
            "Git revision the plan was written against. STRONGLY RECOMMENDED: "
            "without it, files are read from the working tree, which may be on "
            "another branch or behind."
        ),
    )
    args = ap.parse_args()

    # Announce what is actually being measured against. Scoring a plan about a
    # MOVING repository against whatever happens to be checked out is not a
    # measurement, and the failure is silent: a stale tree reports correct
    # citations as "line is past end of file".
    #
    # This cost a real false conclusion - a plan scored 71% grounded against a
    # tree 31 commits behind, and 98% against the right one. The banner exists
    # so the next reader can see the discrepancy rather than discover it.
    resolved = _describe_tree(args.repo, args.rev)
    print(f"scoring against: {resolved}")
    print()

    citations = extract(args.plan.read_text())
    if not citations:
        # Not a pass. A plan with no citations made no checkable claim about the
        # code, which is its own quality signal and should not read as 100%.
        print("NO CITATIONS - the plan makes no verifiable claim about the code.")
        return 2

    verdicts = verify(citations, args.repo, args.rev)
    grounded = [v for v in verdicts if v.ok]
    exact = [v for v in grounded if v.exact]
    for v in verdicts:
        mark = "ok " if v.ok and v.exact else ("~  " if v.ok else "BAD")
        print(f"  [{mark}] {v.citation.label:<62} {v.reason}")

    n = len(verdicts)
    print()
    print(
        f"  GROUNDED  {len(grounded)}/{n} ({100.0 * len(grounded) / n:.0f}%)  cite a real file at a real line"
    )
    print(f"  EXACT     {len(exact)}/{n} ({100.0 * len(exact) / n:.0f}%)  path usable as written")
    print()
    print("  Grounded is the trust signal; exact is citation hygiene. A plan can")
    print("  be fully grounded and score 0% exact - that is a formatting problem,")
    print("  not a fabrication problem, and the two must not be reported as one.")
    return 0 if len(grounded) == n else 1


if __name__ == "__main__":
    sys.exit(main())
