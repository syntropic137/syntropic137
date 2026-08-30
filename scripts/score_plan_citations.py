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
import subprocess
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
        # `is not None`, not truthiness: `:1-0` rendered as `:1`, hiding a
        # malformed range behind a well-formed-looking label.
        suffix = f"-{self.end}" if self.end is not None else ""
        return f"{self.path}:{self.line}{suffix}"

    @property
    def well_formed(self) -> bool:
        """A range that could address anything. `10-2` and `1-0` cannot."""
        if self.line < 1:
            return False
        return self.end is None or self.end >= self.line

    def in_range(self, total: int) -> bool:
        """Whether this citation addresses real lines in a file of `total`.

        End is inclusive, which is how every editor and reviewer reads
        `file.py:10-20`. Stated here because it was previously assumed.
        """
        if not self.well_formed:
            return False
        return self.line <= total and (self.end is None or self.end <= total)


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


def strip_examples(text: str) -> str:
    """Blank out FENCED blocks only, keeping line structure.

    Inline code is deliberately NOT stripped. The obvious-looking version of
    this also blanked `backticked` spans as "examples", which silently deleted
    every real citation in every plan measured so far -- these plans write
    citations as `path/to/file.py:12-30`, because that is the ordinary
    markdown convention for naming a file. Scoring went to NO CITATIONS on all
    five runs, which is how it was caught. Fenced blocks are where a document
    demonstrates its own format; inline code is where it names things.

    A plan that DEMONSTRATES the citation format inside a fence is not making
    that claim, but the extractor could not tell the difference and counted it.
    That inflates the denominator with citations the author never asserted, and
    it inflates it most for the plans that document their own conventions.

    Replaced with blanks rather than deleted so any future line-based reporting
    still points at the right line.
    """
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def extract(text: str) -> list[Citation]:
    """Every distinct cited LOCATION, in order of first appearance.

    Keyed on the canonical span, not the literal text: `x.py:5` and `x.py:5-5`
    name the same line and were counted as two separate citations, so a plan
    that varied its spelling scored against a larger denominator than one that
    did not. Malformed spans are kept -- they are a real defect and must be
    reported, not silently dropped.
    """
    seen: dict[tuple[str, int, int | None], Citation] = {}
    for m in _CITATION.finditer(strip_examples(text)):
        end = int(m["end"]) if m["end"] else None
        c = Citation(m["path"], int(m["line"]), end)
        # A single-line span and an explicit N-N span are the same location.
        canonical = (c.path, c.line, None if end == c.line else end)
        seen.setdefault(canonical, c)
    return list(seen.values())


class RevisionError(RuntimeError):
    """The requested revision could not be used. Never downgrade this.

    A scorer that falls back to the working tree when a revision fails is
    worse than one that crashes: it fails toward "looks good". That is not
    hypothetical -- before this, `--rev definitely-no-such-rev` and a file
    absent at the revision BOTH scored 100%.
    """


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)


def resolve_revision(repo: Path, rev: str) -> str:
    """Pin `rev` to one immutable commit OID, or refuse to score.

    Resolved ONCE, up front. Resolving per citation would let a branch move
    mid-run and score different citations against different trees.
    """
    result = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    if result.returncode != 0 or not result.stdout.strip():
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RevisionError(f"cannot resolve revision {rev!r}" + (f": {detail}" if detail else ""))
    return result.stdout.decode().strip()


def tracked_blobs_at(repo: Path, oid: str) -> set[str]:
    """Every regular file path at a commit. Trees and gitlinks excluded.

    `git show <rev>:some/dir` succeeds and prints a directory listing, which
    the previous version counted as ~49 "lines" of a file that is not a file.
    """
    result = _git(repo, "ls-tree", "-r", "--full-tree", "-z", oid)
    if result.returncode != 0:
        raise RevisionError(f"cannot list tree at {oid}")
    paths: set[str] = set()
    for entry in result.stdout.split(b"\x00"):
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        fields = meta.split()
        # mode type oid -- only regular and executable blobs are citable.
        if len(fields) >= 2 and fields[1] == b"blob" and fields[0] in (b"100644", b"100755"):
            paths.add(path.decode("utf-8", errors="surrogateescape"))
    return paths


def _blob_line_count(repo: Path, oid: str, path: str) -> int | None:
    """Lines in a blob, or None when it is not readable text.

    Bytes, not text=True: a binary blob must not crash the scorer, and a file
    with no trailing newline must not lose its last line the way counting
    "\n" characters did.
    """
    result = _git(repo, "show", f"{oid}:{path}")
    if result.returncode != 0:
        return None
    body = result.stdout
    if b"\x00" in body:
        return None
    try:
        return len(body.decode("utf-8").splitlines())
    except UnicodeDecodeError:
        return None


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


def _is_root_relative(cited: str) -> bool:
    """A path usable verbatim from the repo root.

    `./scripts/x.py` and `../elsewhere/scripts/x.py` both used to score EXACT
    because resolution went through the filesystem. The second can leave the
    repository entirely.
    """
    if cited.startswith("/") or "\\" in cited:
        return False
    # Split the RAW string, not PurePosixPath: it normalizes "./x" to "x", so
    # the "." segment vanishes and a dot-relative path scores exact.
    segments = cited.split("/")
    return bool(segments) and not any(seg in ("", ".", "..") for seg in segments)


def _suffix_match(cited: str, candidates: set[str]) -> str | None:
    """The single tracked path a shortened citation names, if unambiguous."""
    suffix = "/" + cited
    hits = [c for c in candidates if c == cited or c.endswith(suffix)]
    return hits[0] if len(hits) == 1 else None


def verify_at_revision(citations: list[Citation], repo: Path, oid: str) -> list[Verdict]:
    """Score against one immutable tree. No working tree is consulted at all.

    Absent at the revision means NOT grounded -- that is the whole point. The
    previous version fell back to the checkout here, so a citation to a file
    that exists locally but not at the scored revision scored perfectly.
    """
    tracked = tracked_blobs_at(repo, oid)
    lines: dict[str, int | None] = {}
    out: list[Verdict] = []
    for c in citations:
        exact = _is_root_relative(c.path) and c.path in tracked
        resolved = c.path if exact else _suffix_match(c.path, tracked)
        ambiguous = not exact and resolved is None and _suffix_match(c.path, tracked) is None
        if resolved is None:
            out.append(Verdict(c, False, False, False, ambiguous and c.path not in tracked))
            continue
        if resolved not in lines:
            lines[resolved] = _blob_line_count(repo, oid, resolved)
        total = lines[resolved]
        line_ok = total is not None and c.in_range(total)
        out.append(Verdict(c, True, line_ok, exact, False))
    return out


def verify(citations: list[Citation], repo: Path, rev: str | None = None) -> list[Verdict]:
    if rev is not None:
        return verify_at_revision(citations, repo, resolve_revision(repo, rev))
    out: list[Verdict] = []
    for c in citations:
        target, ambiguous = _resolve(repo, c.path)
        exists = target is not None
        exact = exists and _is_root_relative(c.path) and target == (repo / c.path)
        line_ok = False
        if target is not None:
            try:
                with target.open("rb") as fh:
                    total = sum(1 for _ in fh)
                line_ok = c.in_range(total)
            except OSError:
                line_ok = False
        out.append(Verdict(c, exists, line_ok, bool(exact), ambiguous))
    return out


def _describe_tree(repo: Path, rev: str | None) -> str:
    """What the caller is actually being scored against, stated plainly."""

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

    try:
        verdicts = verify(citations, args.repo, args.rev)
    except RevisionError as exc:
        # Exit rather than degrade. A scorer that falls back to the working
        # tree when the revision is unusable fails toward "looks good", which
        # is the one direction a measuring instrument must never fail in.
        print(f"REFUSING TO SCORE: {exc}", file=sys.stderr)
        return 2
    grounded = [v for v in verdicts if v.ok]
    exact = [v for v in grounded if v.exact]
    for v in verdicts:
        mark = "ok " if v.ok and v.exact else ("~  " if v.ok else "BAD")
        print(f"  [{mark}] {v.citation.label:<62} {v.reason}")

    n = len(verdicts)
    print()
    print(
        f"  RESOLVES  {len(grounded)}/{n} ({100.0 * len(grounded) / n:.0f}%)  address points at a real file and real lines"
    )
    print(
        f"  EXACT     {len(exact)}/{n} ({100.0 * len(exact) / n:.0f}%)  path usable verbatim from the repo root"
    )
    print()
    print("  RESOLVES is an ADDRESS check, not a grounding check. It proves the")
    print("  cited lines exist. It does NOT prove they support the claim they are")
    print("  attached to - any invented claim followed by a real file:line scores")
    print("  here. It was called GROUNDED until 2026-08-30, which overstated it.")
    print()
    print("  EXACT is citation hygiene. A plan can fully resolve and score 0%")
    print("  exact: that is a formatting problem, not a fabrication problem.")
    return 0 if len(grounded) == n else 1


if __name__ == "__main__":
    sys.exit(main())
