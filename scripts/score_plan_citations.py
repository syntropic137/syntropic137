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

    @property
    def ok(self) -> bool:
        return self.file_exists and self.line_exists

    @property
    def reason(self) -> str:
        if not self.file_exists:
            return "file does not exist"
        if not self.line_exists:
            return "line is past end of file"
        return "ok"


def extract(text: str) -> list[Citation]:
    """Every distinct file:line citation, in order of first appearance."""
    seen: dict[str, Citation] = {}
    for m in _CITATION.finditer(text):
        c = Citation(m["path"], int(m["line"]), int(m["end"]) if m["end"] else None)
        seen.setdefault(c.label, c)
    return list(seen.values())


def verify(citations: list[Citation], repo: Path) -> list[Verdict]:
    out: list[Verdict] = []
    for c in citations:
        target = repo / c.path
        exists = target.is_file()
        line_ok = False
        if exists:
            try:
                # Count lines without loading the whole file into memory.
                with target.open("rb") as fh:
                    total = sum(1 for _ in fh)
                line_ok = 1 <= c.line <= total and (c.end is None or c.end <= total)
            except OSError:
                line_ok = False
        out.append(Verdict(c, exists, line_ok))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", type=Path)
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    args = ap.parse_args()

    citations = extract(args.plan.read_text())
    if not citations:
        # Not a pass. A plan with no citations made no checkable claim about the
        # code, which is its own quality signal and should not read as 100%.
        print("NO CITATIONS - the plan makes no verifiable claim about the code.")
        return 2

    verdicts = verify(citations, args.repo)
    good = [v for v in verdicts if v.ok]
    for v in verdicts:
        mark = "ok " if v.ok else "BAD"
        print(f"  [{mark}] {v.citation.label:<62} {v.reason}")

    pct = 100.0 * len(good) / len(verdicts)
    print()
    print(f"citations: {len(good)}/{len(verdicts)} resolve ({pct:.0f}%)")
    return 0 if len(good) == len(verdicts) else 1


if __name__ == "__main__":
    sys.exit(main())
