"""Generate the root CHANGELOG.md from merged pull requests.

Run it through just, never by hand-editing the file:

    just changelog                     # regenerate CHANGELOG.md
    just changelog-check               # exit 1 (with a diff) if it is stale
    just changelog --release 0.34.0    # what `just bump-version` runs

Pull requests never edit CHANGELOG.md. Around ten agent PRs are open at any
time, and a file every one of them appends to would conflict on every merge.
The file is a pure function of the repository's history instead, regenerated
in the release flow so each release PR carries it current.

WHERE THE DATA COMES FROM. Git is the primary source, and the only one that
decides structure: which PRs exist, which release each belongs to, its date and
its order. A PR is a merge commit whose subject is ``Merge pull request #N from
<owner>/<branch>`` and whose body is the PR title, which is what GitHub writes.
Git is primary because it is the only source that knows release membership -
a release is ``git log vPREV..vX`` - and because it works offline, in CI and in
an agent workspace, and gives the same answer every time.

GitHub (``gh``) is consulted for exactly one thing git does not carry: the PR
body, for its ``## Release notes`` section. When ``gh`` is missing, not
authenticated or ``--offline`` is passed, every entry falls back to its PR
title, so offline and online output differ only in the wording of entries that
have release notes - never in which PRs appear or where.

Three facts about this repository the walk depends on:

- Release tags live on the ``release`` branch, not on ``main``, so a release is
  computed tag-to-tag and the unreleased range is ``vLATEST..HEAD``; nothing
  here asks whether a tag is an ancestor of HEAD.
- Some PRs reach main through another merge, so the walk is not
  ``--first-parent``. Only the subject GitHub writes is matched; hand-written
  merges such as ``Merge #1595 (...)`` would otherwise list a PR twice.
- The main -> release PR (``... from <owner>/main``) is the release itself, not
  a change, and is skipped.

Prerelease tags (``v0.32.0-beta.3``) are not sections: their changes are listed
under the stable release that ships them.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/syntropic137/syntropic137"

# The changelog starts here. Earlier releases are described on GitHub's
# releases page, which the header links to, rather than reconstructed from
# merge subjects nobody wrote for this purpose.
FIRST_VERSION = (0, 33, 1)

STABLE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
STABLE_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
MERGE_SUBJECT = re.compile(r"^Merge pull request #(\d+) from (\S+)$")
CONVENTIONAL_TYPE = re.compile(r"^(\w+)(?:\([^)]*\))?!?:\s*(.*)$")
RELEASE_NOTES_HEADING = re.compile(r"^#{1,6}\s*release notes\s*:?\s*$", re.IGNORECASE)
HEADING = re.compile(r"^#{1,6}\s")
FENCE = re.compile(r"^\s*(```|~~~)")
BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
DASHES = re.compile("\\s*[\N{EM DASH}\N{EN DASH}]\\s*")
TRAILING_PR_REF = re.compile(r"\s*\(#\d+\)$")

# Unit and record separators: neither can appear in a commit message.
FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"


class Category(Enum):
    """Keep a Changelog 1.1.0 categories, in the order the spec lists them."""

    ADDED = "Added"
    CHANGED = "Changed"
    DEPRECATED = "Deprecated"
    REMOVED = "Removed"
    FIXED = "Fixed"
    SECURITY = "Security"


TYPE_CATEGORIES: Mapping[str, Category] = {
    "feat": Category.ADDED,
    "fix": Category.FIXED,
    "security": Category.SECURITY,
}
# Keep a Changelog entries lead with their verb, so the first word decides.
LEADING_VERB_CATEGORIES: Sequence[tuple[re.Pattern[str], Category]] = (
    (re.compile(r"^(remove[sd]?|removing|delete[sd]?|drop(s|ped)?)\b", re.I), Category.REMOVED),
    (re.compile(r"^deprecat(e|es|ed|ing)\b", re.I), Category.DEPRECATED),
)


@dataclass(frozen=True)
class Entry:
    """One merged pull request, as it appears in the changelog."""

    number: int
    text: str
    category: Category

    def render(self) -> str:
        return f"- {self.text} (#{self.number})"


@dataclass(frozen=True)
class Section:
    """A ``## [...]`` block: Unreleased, or one stable release."""

    version: str | None  # None is Unreleased
    date: str | None
    previous_version: str | None
    entries: tuple[Entry, ...]

    @property
    def label(self) -> str:
        return self.version if self.version is not None else "Unreleased"

    def heading(self) -> str:
        if self.version is None:
            return "## [Unreleased]"
        return f"## [{self.version}] - {self.date}"

    def link(self, repo_url: str) -> str:
        head = "HEAD" if self.version is None else f"v{self.version}"
        if self.previous_version is None:
            target = f"{repo_url}/releases/tag/{head}"
        else:
            target = f"{repo_url}/compare/v{self.previous_version}...{head}"
        return f"[{self.label.lower()}]: {target}"


@dataclass(frozen=True)
class MergedPullRequest:
    number: int
    title: str
    merged_at: int  # committer timestamp, seconds


@dataclass(frozen=True)
class PendingRelease:
    """The version being cut: its section exists before its tag does."""

    version: str
    date: str


# --- text ---------------------------------------------------------------------


def plain_text(text: str) -> str:
    """One line, ASCII hyphens: em and en dashes become `` - ``."""
    text = DASHES.sub(" - ", text)
    return " ".join(text.split())


def release_notes_bullet(body: str) -> str | None:
    """The first bullet of a ``## Release notes`` section, joined to one line.

    Continuation lines of that bullet are kept; the next bullet, a blank line,
    a code fence or the next heading ends it. Fenced code is not prose: a YAML
    list inside a fence is not a bullet. A section written as paragraphs has
    no bullet, and the caller falls back to the PR title.
    """
    lines = body.replace("\r\n", "\n").split("\n")
    in_section = False
    in_fence = False
    collected: list[str] = []
    for line in lines:
        # Fences are tracked from the first line: a ``## Release notes`` inside
        # a fenced example is code, not the section.
        if FENCE.match(line):
            if collected:
                break
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not in_section:
            in_section = RELEASE_NOTES_HEADING.match(line.strip()) is not None
            continue
        if HEADING.match(line):
            break
        if not collected:
            bullet = BULLET.match(line)
            if bullet is not None and bullet.group(1).strip():
                collected.append(bullet.group(1))
            continue
        if not line.strip() or BULLET.match(line) is not None:
            break
        collected.append(line)
    if not collected:
        return None
    return plain_text(" ".join(part.strip() for part in collected))


def categorize(title: str, notes: str | None) -> Category:
    """feat/fix/security by conventional type; otherwise the leading verb."""
    match = CONVENTIONAL_TYPE.match(title)
    commit_type = match.group(1).lower() if match else ""
    by_type = TYPE_CATEGORIES.get(commit_type)
    if by_type is not None:
        return by_type
    description = match.group(2) if match else title
    for text in (notes, description):
        if text is None:
            continue
        for pattern, category in LEADING_VERB_CATEGORIES:
            if pattern.match(text):
                return category
    return Category.CHANGED


def make_entry(pr: MergedPullRequest, body: str | None) -> Entry:
    title = plain_text(pr.title)
    notes = release_notes_bullet(body) if body is not None else None
    text = TRAILING_PR_REF.sub("", notes) if notes is not None else title
    return Entry(number=pr.number, text=text, category=categorize(title, notes))


# --- git ----------------------------------------------------------------------


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def stable_tags(repo: Path) -> list[tuple[tuple[int, int, int], str]]:
    """Every ``vX.Y.Z`` tag, newest version first; prereleases excluded."""
    tags: list[tuple[tuple[int, int, int], str]] = []
    for name in git(repo, "tag", "--list", "v*").split():
        match = STABLE_TAG.match(name)
        if match is not None:
            version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            tags.append((version, name))
    return sorted(tags, reverse=True)


def tag_date(repo: Path, tag: str) -> str:
    """The tagged commit's date in UTC, so the output never depends on a TZ."""
    stamp = int(git(repo, "log", "-1", "--format=%ct", f"{tag}^{{commit}}").strip())
    return dt.datetime.fromtimestamp(stamp, dt.UTC).date().isoformat()


class IncompleteHistoryError(Exception):
    """The clone cannot answer which PRs shipped in which release."""


def require_complete_history(repo: Path, first_version: tuple[int, int, int]) -> None:
    """Refuse a shallow clone or one without release tags.

    CI's default checkout is ``fetch-depth: 1`` without tags. There, ``git log``
    finds no merges and no tags, and the changelog would be silently rewritten
    as an empty Unreleased section. Failing is the only honest answer.
    """
    fix = "run `git fetch --unshallow --tags origin` (or check out with fetch-depth: 0)"
    if git(repo, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise IncompleteHistoryError(f"shallow clone: merge history is missing; {fix}")
    if not any(version >= first_version for version, _ in stable_tags(repo)):
        floor = ".".join(str(part) for part in first_version)
        raise IncompleteHistoryError(f"no release tag at or after v{floor}; {fix}")


def merged_pull_requests(repo: Path, rev_range: str) -> list[MergedPullRequest]:
    """PRs merged in ``rev_range``, newest first, ties broken by PR number."""
    log = git(
        repo,
        "log",
        "--merges",
        f"--format=%ct{FIELD_SEP}%s{FIELD_SEP}%b{RECORD_SEP}",
        rev_range,
    )
    found: dict[int, MergedPullRequest] = {}
    for record in log.split(RECORD_SEP):
        fields = record.strip("\n").split(FIELD_SEP)
        if len(fields) != 3:
            continue
        stamp, subject, body = fields
        match = MERGE_SUBJECT.match(subject.strip())
        if match is None or match.group(2).endswith("/main"):
            continue
        number = int(match.group(1))
        title = next((line for line in body.splitlines() if line.strip()), subject)
        if number not in found:
            found[number] = MergedPullRequest(number, title.strip(), int(stamp))
    return sorted(found.values(), key=lambda pr: (-pr.merged_at, -pr.number))


# --- GitHub (optional) ----------------------------------------------------------


def fetch_bodies(repo: Path, since: int) -> dict[int, str]:
    """PR bodies from GitHub for PRs merged since ``since``; empty if unavailable."""
    if shutil.which("gh") is None:
        print("changelog: gh not found; using PR titles only", file=sys.stderr)
        return {}
    day = dt.datetime.fromtimestamp(since, dt.UTC).date() - dt.timedelta(days=1)
    try:
        output = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                REPO_URL.removeprefix("https://github.com/"),
                "--state",
                "merged",
                "--limit",
                "2000",
                "--search",
                f"merged:>={day.isoformat()}",
                "--json",
                "number,body",
            ],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        print(
            f"changelog: gh failed ({error.stderr.strip()}); using PR titles only", file=sys.stderr
        )
        return {}
    bodies: dict[int, str] = {}
    for item in json.loads(output):
        if isinstance(item, dict):
            number = item.get("number")
            body = item.get("body")
            if isinstance(number, int) and isinstance(body, str):
                bodies[number] = body
    return bodies


# --- assembly -------------------------------------------------------------------


def collect_sections(
    repo: Path,
    pending: PendingRelease | None = None,
    first_version: tuple[int, int, int] = FIRST_VERSION,
) -> list[tuple[Section, list[MergedPullRequest]]]:
    """Every section, newest first, with the PRs that belong to it (no text yet)."""
    require_complete_history(repo, first_version)
    tags = stable_tags(repo)
    latest = tags[0][1] if tags else None
    unreleased_prs = merged_pull_requests(repo, f"{latest}..HEAD" if latest else "HEAD")
    latest_version = latest.removeprefix("v") if latest else None

    sections: list[tuple[Section, list[MergedPullRequest]]] = []
    if pending is not None:
        sections.append((Section(None, None, pending.version, ()), []))
        sections.append(
            (Section(pending.version, pending.date, latest_version, ()), unreleased_prs)
        )
    else:
        sections.append((Section(None, None, latest_version, ()), unreleased_prs))

    for index, (version, tag) in enumerate(tags):
        if version < first_version:
            break
        previous = tags[index + 1][1] if index + 1 < len(tags) else None
        prs = merged_pull_requests(repo, f"{previous}..{tag}" if previous else tag)
        section = Section(
            tag.removeprefix("v"),
            tag_date(repo, tag),
            previous.removeprefix("v") if previous else None,
            (),
        )
        sections.append((section, prs))
    return sections


def render(sections: Sequence[Section], repo_url: str = REPO_URL) -> str:
    oldest = sections[-1].label
    lines = [
        "# Changelog",
        "",
        "All notable changes to this project are documented in this file.",
        "",
        "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),",
        "and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).",
        "",
        "This file is generated by `just changelog` (scripts/changelog.py) from merged",
        "pull requests. Do not edit it by hand; pull requests never touch it.",
        f"Releases before {oldest} are described in [GitHub releases]({repo_url}/releases).",
    ]
    for section in sections:
        lines += ["", section.heading()]
        for category in Category:
            entries = [entry for entry in section.entries if entry.category is category]
            if entries:
                lines += ["", f"### {category.value}", ""]
                lines += [entry.render() for entry in entries]
    lines.append("")
    lines += [section.link(repo_url) for section in sections]
    return "\n".join(lines) + "\n"


def build_changelog(
    repo: Path,
    bodies: Mapping[int, str] | None = None,
    pending: PendingRelease | None = None,
    first_version: tuple[int, int, int] = FIRST_VERSION,
    repo_url: str = REPO_URL,
) -> str:
    """The complete CHANGELOG.md text. ``bodies`` maps PR number to PR body."""
    known = bodies or {}
    sections = [
        Section(
            section.version,
            section.date,
            section.previous_version,
            tuple(make_entry(pr, known.get(pr.number)) for pr in prs),
        )
        for section, prs in collect_sections(repo, pending, first_version)
    ]
    return render(sections, repo_url)


def oldest_merge(repo: Path, first_version: tuple[int, int, int]) -> int | None:
    stamps = [pr.merged_at for _, prs in collect_sections(repo, None, first_version) for pr in prs]
    return min(stamps) if stamps else None


def pending_release(version: str | None, date: str | None) -> PendingRelease | None:
    """The release being cut, or None for a prerelease (betas get no section)."""
    if version is None:
        return None
    version = version.removeprefix("v")
    if STABLE_VERSION.match(version) is None:
        print(f"changelog: {version} is a prerelease; leaving it under Unreleased", file=sys.stderr)
        return None
    return PendingRelease(version, date or dt.datetime.now(dt.UTC).date().isoformat())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    parser.add_argument("--offline", action="store_true", help="git only; do not call gh")
    parser.add_argument("--release", metavar="X.Y.Z", help="file Unreleased under this version")
    parser.add_argument(
        "--date", metavar="YYYY-MM-DD", help="date for --release (default: today, UTC)"
    )
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "CHANGELOG.md")
    args = parser.parse_args(argv)

    release: str | None = args.release
    date: str | None = args.date
    pending = pending_release(release, date)
    bodies: dict[int, str] = {}
    try:
        if not args.offline:
            since = oldest_merge(REPO_ROOT, FIRST_VERSION)
            if since is not None:
                bodies = fetch_bodies(REPO_ROOT, since)
        text = build_changelog(REPO_ROOT, bodies, pending)
    except IncompleteHistoryError as error:
        print(f"changelog: {error}; nothing written", file=sys.stderr)
        return 2

    output: Path = args.output
    if args.check:
        current = output.read_text() if output.exists() else ""
        if current == text:
            print(f"{output.name} is up to date")
            return 0
        sys.stdout.writelines(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                text.splitlines(keepends=True),
                f"{output.name} (committed)",
                f"{output.name} (generated)",
            )
        )
        print(f"\n{output.name} is stale: run `just changelog`", file=sys.stderr)
        return 1
    output.write_text(text)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
