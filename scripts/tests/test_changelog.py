"""CHANGELOG.md is generated from merged PRs; these pin how.

The release-sectioning tests run the generator against a real throwaway git
repository built to the shape this one has: PRs merged into ``main``, release
tags on a separate ``release`` branch (never an ancestor of main), a beta tag,
the main -> release PR, a hand-written ``Merge #N (...)`` merge and a PR that
reached main through another branch. A second repository adds ``Merge #N: ...``
merges, both this repository's and a subtree's (#1878). No network: PR bodies
are passed in.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import changelog
from changelog import (
    Category,
    IncompleteHistoryError,
    MergedPullRequest,
    PendingRelease,
    build_changelog,
    categorize,
    make_entry,
    pending_release,
    plain_text,
    release_notes_bullet,
)

URL = "https://example.test/org/repo"
EM_DASH = "\N{EM DASH}"
EN_DASH = "\N{EN DASH}"


# --- grouping -----------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("title", "notes", "expected"),
    [
        ("feat(api): add a thing", None, Category.ADDED),
        ("feat!: breaking thing", None, Category.ADDED),
        ("fix(#12): repair a thing", None, Category.FIXED),
        ("security(deps): clear advisories", None, Category.SECURITY),
        # The type decides, not a scope that happens to say security.
        ("ci(security): pin actions", None, Category.CHANGED),
        ("chore: remove the legacy poller", None, Category.REMOVED),
        ("refactor(cli): drop the --old flag", None, Category.REMOVED),
        ("chore: deprecate EventSubscriptionService", None, Category.DEPRECATED),
        ("chore: tidy", "Removed `syn foo`; use `syn bar`.", Category.REMOVED),
        ("chore: tidy", "Deprecated `syn foo`.", Category.DEPRECATED),
        # Only the leading verb counts; a mention mid-sentence does not.
        ("docs: explain why we remove stale keys", None, Category.CHANGED),
        ("Bump the thing", None, Category.CHANGED),
        # feat/fix/security win over the verb.
        ("fix: remove a race", None, Category.FIXED),
    ],
)
def test_categorize(title: str, notes: str | None, expected: Category) -> None:
    assert categorize(title, notes) is expected


# --- release notes ------------------------------------------------------------


@pytest.mark.unit
def test_release_notes_first_bullet_with_continuation() -> None:
    body = (
        "## Summary\n\n- not this one\n\n"
        "## Release notes\n\n"
        "- `syn run` now streams\n  its output live.\n"
        "- second bullet\n\n## Test plan\n- nope\n"
    )
    assert release_notes_bullet(body) == "`syn run` now streams its output live."


@pytest.mark.unit
def test_release_notes_skips_fenced_code_and_prose_only_has_no_bullet() -> None:
    fenced = "## Release notes\n\nCaps:\n\n```yaml\n- name: x\n```\n\n* the real bullet\n"
    assert release_notes_bullet(fenced) == "the real bullet"
    prose = "## Release notes\n\nWorkflows can now cap cost.\n\n## Testing\n- a bullet\n"
    assert release_notes_bullet(prose) is None
    assert release_notes_bullet("## Summary\n- a bullet\n") is None


@pytest.mark.unit
def test_release_notes_heading_inside_a_fence_is_not_the_section() -> None:
    body = (
        "## Summary\n\nPR template example:\n\n"
        "```markdown\n## Release notes\n- This text is an example, not a release note.\n```\n\n"
        "## Release notes\n\n- The real shipped change.\n"
    )
    assert release_notes_bullet(body) == "The real shipped change."
    tilde = "~~~\n## Release notes\n- example\n~~~\nno real section\n"
    assert release_notes_bullet(tilde) is None


@pytest.mark.unit
def test_entry_prefers_release_note_and_drops_its_trailing_pr_ref() -> None:
    pr = MergedPullRequest(42, "feat(cli): add tags", 0)
    body = "### Release notes\r\n- Executions can carry tags " + EM_DASH + " repeatable (#42)\r\n"
    entry = make_entry(pr, body)
    assert entry.render() == "- Executions can carry tags - repeatable (#42)"
    assert entry.category is Category.ADDED
    assert make_entry(pr, None).render() == "- feat(cli): add tags (#42)"


# --- em dashes ----------------------------------------------------------------


@pytest.mark.unit
def test_plain_text_replaces_em_and_en_dashes() -> None:
    assert plain_text("fix: a" + EM_DASH + "b " + EN_DASH + " c  d") == "fix: a - b - c d"


# --- prerelease handling ------------------------------------------------------


@pytest.mark.unit
def test_prerelease_gets_no_section() -> None:
    assert pending_release("0.34.0-beta.1", "2026-10-07") is None
    assert pending_release("v0.34.0", "2026-10-07") == PendingRelease("0.34.0", "2026-10-07")


# --- tag sectioning against a real repository ---------------------------------


def _git(repo: Path, *args: str, when: int | None = None) -> None:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.test",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.test",
        "HOME": str(repo),
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    if when is not None:
        stamp = f"@{when} +0000"
        env |= {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


DAY = 86_400
T0 = 1_790_000_000  # 2026-09-21 UTC


def _merge_pr(
    repo: Path,
    number: int,
    branch: str,
    title: str,
    when: int,
    into: str = "main",
    subject: str | None = None,
    body: str | None = None,
) -> None:
    """Merge a one-commit branch; GitHub's default subject and body unless given."""
    _git(repo, "checkout", "-q", "-b", branch, into)
    (repo / f"{number}.txt").write_text(title)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", title, when=when)
    _git(repo, "checkout", "-q", into)
    message = ["-m", subject or f"Merge pull request #{number} from org/{branch}"]
    if body != "":
        message += ["-m", body or title]
    _git(repo, "merge", "-q", "--no-ff", branch, *message, when=when)


def _release(repo: Path, tag: str, when: int, release_pr: int) -> None:
    _git(repo, "checkout", "-q", "release")
    _git(
        repo,
        "merge",
        "-q",
        "--no-ff",
        "main",
        "-m",
        f"Merge pull request #{release_pr} from org/main",
        "-m",
        "Release",
        when=when,
    )
    _git(repo, "tag", tag)
    _git(repo, "checkout", "-q", "main")


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("history")
    _git(path, "init", "-q", "-b", "main")
    (path / "README").write_text("x")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "root", when=T0)
    _git(path, "branch", "release")

    _merge_pr(path, 1, "feat/one", "feat: first feature", T0 + DAY)
    _release(path, "v0.1.0", T0 + DAY + 60, release_pr=2)

    _merge_pr(path, 3, "fix/three", "fix: before the beta", T0 + 2 * DAY)
    _git(path, "tag", "v0.2.0-beta.1")
    _merge_pr(path, 4, "chore/four", "chore: remove the old flag", T0 + 3 * DAY)
    _release(path, "v0.2.0", T0 + 3 * DAY + 60, release_pr=5)

    # A PR that reached main via another branch, merged by hand as `Merge #6`;
    # not on main's first-parent line, so a --first-parent walk would miss #7.
    _git(path, "branch", "side", "main")
    _merge_pr(
        path, 7, "feat/seven", "feat: nested " + EM_DASH + " via side", T0 + 4 * DAY, into="side"
    )
    _git(path, "checkout", "-q", "main")
    _git(
        path,
        "merge",
        "-q",
        "--no-ff",
        "side",
        "-m",
        "Merge #6 (side work) into main",
        when=T0 + 5 * DAY,
    )
    _merge_pr(path, 8, "security/eight", "security(deps): bump", T0 + 6 * DAY)
    return path


@pytest.mark.unit
def test_sections_by_tag_newest_first(repo: Path) -> None:
    text = build_changelog(
        repo, {8: "## Release notes\n- Patched a CVE.\n"}, repo_url=URL, first_version=(0, 0, 0)
    )
    expected_tail = """
## [Unreleased]

### Added

- feat: nested - via side (#7)

### Security

- Patched a CVE. (#8)

## [0.2.0] - 2026-09-24

### Removed

- chore: remove the old flag (#4)

### Fixed

- fix: before the beta (#3)

## [0.1.0] - 2026-09-22

### Added

- feat: first feature (#1)

[unreleased]: https://example.test/org/repo/compare/v0.2.0...HEAD
[0.2.0]: https://example.test/org/repo/compare/v0.1.0...v0.2.0
[0.1.0]: https://example.test/org/repo/releases/tag/v0.1.0
"""
    assert text.endswith(expected_tail)
    # Release PRs (from org/main) and the hand-written `Merge #6` never appear.
    assert "(#2)" not in text and "(#5)" not in text and "(#6)" not in text


@pytest.mark.unit
def test_first_version_floor_and_pending_release(repo: Path) -> None:
    text = build_changelog(
        repo, pending=PendingRelease("0.3.0", "2026-10-01"), repo_url=URL, first_version=(0, 2, 0)
    )
    assert "## [0.1.0]" not in text
    assert "Releases before 0.2.0 are described in" in text
    unreleased, rest = text.split("## [0.3.0] - 2026-10-01", 1)
    assert unreleased.rstrip().endswith("## [Unreleased]")
    assert "(#7)" in rest.split("## [0.2.0]")[0] and "(#8)" in rest.split("## [0.2.0]")[0]
    assert text.endswith(
        "[unreleased]: https://example.test/org/repo/compare/v0.3.0...HEAD\n"
        "[0.3.0]: https://example.test/org/repo/compare/v0.2.0...v0.3.0\n"
        "[0.2.0]: https://example.test/org/repo/compare/v0.1.0...v0.2.0\n"
    )


@pytest.mark.unit
def test_output_is_deterministic(repo: Path) -> None:
    first = build_changelog(repo, repo_url=URL, first_version=(0, 0, 0))
    assert first == build_changelog(repo, repo_url=URL, first_version=(0, 0, 0))


@pytest.fixture(scope="module")
def named_merges_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Main with ``Merge #N: ...`` merges, and a subtree that brought its own."""
    path = tmp_path_factory.mktemp("named")
    _git(path, "init", "-q", "-b", "main")
    (path / "README").write_text("x")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "root", when=T0)
    _git(path, "branch", "release")
    _merge_pr(path, 1, "feat/one", "feat: first feature", T0 + DAY)
    _release(path, "v0.1.0", T0 + DAY + 60, release_pr=2)

    # `gh pr merge --subject "Merge #N: ..."`: the body is the PR title...
    _merge_pr(
        path,
        11,
        "feat/eleven",
        "feat(landing): rebuilt landing page",
        T0 + 2 * DAY,
        subject="Merge #11: rebuilt landing page",
    )
    # ...or empty, when only the subject carries the title.
    _merge_pr(
        path,
        12,
        "fix/twelve",
        "fix: unused commit title",
        T0 + 3 * DAY,
        subject="Merge #12: fix: deploy docs from release only",
        body="",
    )

    # Another repository's history, with its own root and its own PR numbers,
    # joined in the way `git subtree add` joins it.
    _git(path, "checkout", "-q", "--orphan", "landing")
    _git(path, "rm", "-rfq", ".")
    (path / "index.html").write_text("landing")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "landing root", when=T0)
    _merge_pr(
        path,
        28,
        "lp-twenty-eight",
        "feat: name the supported harnesses",
        T0 + 4 * DAY,
        into="landing",
        subject="Merge #28: name the supported harnesses",
    )
    _git(path, "checkout", "-q", "main")
    _git(
        path,
        "merge",
        "-q",
        "--allow-unrelated-histories",
        "-s",
        "ours",
        "landing",
        "-m",
        "Add 'apps/syn-landing/' from commit landing",
        when=T0 + 5 * DAY,
    )
    return path


def _sha(repo: Path, rev: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", rev], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.mark.unit
def test_named_merge_subjects_count_only_when_confirmed(
    named_merges_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merges = {
        int(number): _sha(named_merges_repo, f":/^Merge #{number}:")
        for number in (11, 12, 28)
    }
    # #28 is the subtree's PR, and is deliberately not confirmed.
    monkeypatch.setattr(
        changelog,
        "CUSTOM_SUBJECT_MERGES",
        {merges[11]: 11, merges[12]: 12},
    )
    text = build_changelog(
        named_merges_repo,
        {11: "## Release notes\n- syntropic137.com rebuilt.\n"},
        repo_url=URL,
        first_version=(0, 0, 0),
    )
    unreleased = text.split("## [Unreleased]", 1)[1].split("## [0.1.0]", 1)[0]
    assert unreleased == (
        "\n\n### Added\n\n- syntropic137.com rebuilt. (#11)\n"
        "\n### Fixed\n\n- fix: deploy docs from release only (#12)\n\n"
    )
    assert "(#28)" not in text
    # Offline lists the same PRs; only the release-note wording differs.
    offline = build_changelog(named_merges_repo, repo_url=URL, first_version=(0, 0, 0))
    assert "- feat(landing): rebuilt landing page (#11)" in offline
    assert "(#12)" in offline and "(#28)" not in offline


@pytest.mark.unit
def test_named_merge_with_a_confirmed_sha_but_another_number_is_dropped(
    named_merges_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha = _sha(named_merges_repo, ":/^Merge #11:")
    monkeypatch.setattr(changelog, "CUSTOM_SUBJECT_MERGES", {sha: 99})
    text = build_changelog(named_merges_repo, repo_url=URL, first_version=(0, 0, 0))
    assert "(#11)" not in text and "(#99)" not in text


@pytest.mark.unit
def test_shared_root_fork_pr_number_cannot_replace_upstream_pr(tmp_path: Path) -> None:
    upstream, fork = tmp_path / "upstream", tmp_path / "fork"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    (upstream / "README").write_text("x")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-q", "-m", "root", when=T0)
    subprocess.run(["git", "clone", "-q", str(upstream), str(fork)], check=True)
    _merge_pr(fork, 28, "fork-feature", "feat: fork-only", T0 + 2 * DAY, subject="Merge #28: fork-only")
    _merge_pr(upstream, 28, "up-feature", "fix: real upstream PR", T0 + DAY)
    _git(upstream, "fetch", "-q", str(fork), "main:fork-import")
    _git(
        upstream, "merge", "-q", "--no-ff", "-X", "ours", "fork-import",
        "-m", "Merge pull request #99 from contributor/fork-import",
        "-m", "feat: import fork work", when=T0 + 3 * DAY,
    )
    _git(upstream, "tag", "v0.1.0")
    text = build_changelog(upstream, repo_url=URL, first_version=(0, 0, 0))
    assert "- fix: real upstream PR (#28)" in text
    assert "fork-only" not in text
    assert "(#99)" in text


@pytest.mark.unit
def test_custom_subject_release_merge_is_not_listed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "root", when=T0)
    _git(repo, "branch", "release")
    _merge_pr(repo, 11, "feature", "feat: shipped", T0 + DAY, subject="Merge #11: shipped")
    _git(repo, "checkout", "-q", "release")
    _git(
        repo, "merge", "-q", "--no-ff", "main",
        "-m", "Merge #12: Release v0.1.0", "-m", "Release v0.1.0", when=T0 + 2 * DAY,
    )
    _git(repo, "tag", "v0.1.0")
    text = build_changelog(repo, repo_url=URL, first_version=(0, 0, 0))
    assert "(#12)" not in text


# --- incomplete clones --------------------------------------------------------


@pytest.mark.unit
def test_shallow_clone_without_tags_is_refused(repo: Path, tmp_path: Path) -> None:
    # The shape CI's checkout gives: depth 1, no tags.
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--no-tags", f"file://{repo}", str(clone)],
        check=True,
        capture_output=True,
    )
    with pytest.raises(IncompleteHistoryError, match="shallow clone"):
        build_changelog(clone, repo_url=URL, first_version=(0, 0, 0))


@pytest.mark.unit
def test_full_clone_without_tags_is_refused(repo: Path, tmp_path: Path) -> None:
    clone = tmp_path / "untagged"
    subprocess.run(
        ["git", "clone", "-q", "--no-tags", f"file://{repo}", str(clone)],
        check=True,
        capture_output=True,
    )
    with pytest.raises(IncompleteHistoryError, match=r"no release tag at or after v0\.2\.0"):
        build_changelog(clone, repo_url=URL, first_version=(0, 2, 0))
    # Tags older than the first version do not count as the history it needs.
    with pytest.raises(IncompleteHistoryError, match=r"v9\.0\.0"):
        build_changelog(repo, repo_url=URL, first_version=(9, 0, 0))
