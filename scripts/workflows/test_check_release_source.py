"""Tests for scripts/workflows/check_release_source.py, against real git repos.

Each test builds a tiny history: `main` with a fix on it, `release` tagged
v1.0.4, and a hotfix branch cut from that tag. Git itself does the work, so a
cherry-pick, a patch-id or a merge here is the real thing.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from check_release_source import Git, SourceError, bump_files, check_source

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

ALLOWED = frozenset({"pyproject.toml", "CHANGELOG.md"})


def _pyproject(version: str, extra: str = "") -> str:
    return f'[project]\nname = "demo"\nversion = "{version}"\n{extra}'


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True)
        self.git = Git(path)
        self.fix = ""
        self.sh("init", "-q", "-b", "main")
        self.sh("config", "user.name", "t")
        self.sh("config", "user.email", "t@invalid")
        self.sh("config", "commit.gpgsign", "false")

    def sh(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.path, check=True, capture_output=True, text=True
        ).stdout.strip()

    def commit(self, message: str, **files: str) -> str:
        for name, body in files.items():
            target = self.path / name.replace("__", "/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
            self.sh("add", name.replace("__", "/"))
        self.sh("commit", "-q", "--allow-empty", "-m", message)
        return self.sh("rev-parse", "HEAD")

    def check(self, head_ref: str, allowed: frozenset[str] = ALLOWED) -> list[str]:
        return check_source(
            self.git,
            head_ref,
            self.sh("rev-parse", head_ref),
            self.sh("rev-parse", "release"),
            allowed,
            main_ref="main",
        )


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    """main -> release (merge, tagged v1.0.4) -> main gains a fix."""
    r = Repo(tmp_path / "repo")
    r.commit(
        "init", **{"pyproject.toml": _pyproject("1.0.4"), "CHANGELOG.md": "# c\n", "a.txt": "a\n"}
    )
    r.sh("switch", "-q", "-c", "release")
    r.sh("switch", "-q", "main")
    r.commit("feat: unrelated", **{"b.txt": "b\n"})
    r.sh("switch", "-q", "release")
    r.sh("merge", "-q", "--no-ff", "-m", "Merge main", "main")
    r.sh("tag", "v1.0.4")
    r.sh("switch", "-q", "main")
    r.commit("feat: unreleased work", **{"c.txt": "c\n"})
    r.fix = r.commit("security(deps): pin the fix", **{"a.txt": "a fixed\n"})
    return r


def _cut_hotfix(r: Repo, version: str = "1.0.5", base: str = "v1.0.4") -> None:
    r.sh("switch", "-q", "-c", f"hotfix/v{version}", base)


def _bump(r: Repo, version: str = "1.0.5", extra: str = "") -> None:
    r.commit(
        f"chore: bump version to v{version}",
        **{"pyproject.toml": _pyproject(version, extra), "CHANGELOG.md": f"# c\n## [{version}]\n"},
    )


def _good_hotfix(r: Repo) -> None:
    _cut_hotfix(r)
    r.sh("cherry-pick", "-x", r.fix)
    _bump(r)


class TestMain:
    def test_main_is_allowed_when_release_has_only_merges(self, repo: Repo) -> None:
        assert repo.check("main") == ["main carries every commit on release"]

    def test_main_is_refused_until_a_released_hotfix_is_forward_merged(self, repo: Repo) -> None:
        _good_hotfix(repo)
        repo.sh("switch", "-q", "release")
        repo.sh("merge", "-q", "--no-ff", "-m", "Merge hotfix", "hotfix/v1.0.5")
        with pytest.raises(SourceError, match="not forward-merged"):
            repo.check("main")
        repo.sh("switch", "-q", "main")
        repo.sh("merge", "-q", "--no-ff", "-m", "Merge hotfix into main", "hotfix/v1.0.5")
        assert repo.check("main") == ["main carries every commit on release"]


class TestHotfix:
    def test_a_cherry_pick_and_a_bump_off_the_release_tag_pass(self, repo: Repo) -> None:
        _good_hotfix(repo)
        notes = repo.check("hotfix/v1.0.5")
        assert notes[0].startswith("cut from v1.0.4")
        assert notes[-1] == "tree = v1.0.4 + 1 cherry-pick(s) + version bump"

    def test_a_pr_merge_inside_the_hotfix_branch_is_allowed(self, repo: Repo) -> None:
        _cut_hotfix(repo)
        repo.sh("switch", "-q", "-c", "hotfix/v1.0.5-fix")
        repo.sh("cherry-pick", "-x", repo.fix)
        repo.sh("switch", "-q", "hotfix/v1.0.5")
        repo.sh("merge", "-q", "--no-ff", "-m", "Merge pull request #9 from x", "hotfix/v1.0.5-fix")
        _bump(repo)
        assert repo.check("hotfix/v1.0.5")[-1].startswith("tree = v1.0.4 + 1")

    def test_a_commit_that_is_not_a_cherry_pick_is_refused(self, repo: Repo) -> None:
        _good_hotfix(repo)
        repo.commit("fix: sneak", **{"d.txt": "d\n"})
        with pytest.raises(SourceError, match="neither a git cherry-pick -x"):
            repo.check("hotfix/v1.0.5")

    def test_a_cherry_pick_of_a_commit_not_on_main_is_refused(self, repo: Repo) -> None:
        repo.sh("switch", "-q", "-c", "side", "main")
        side = repo.commit("fix: never merged", **{"e.txt": "e\n"})
        _cut_hotfix(repo)
        repo.sh("cherry-pick", "-x", side)
        _bump(repo)
        with pytest.raises(SourceError, match="not on main"):
            repo.check("hotfix/v1.0.5")

    def test_a_cherry_pick_edited_after_the_fact_is_refused(self, repo: Repo) -> None:
        _cut_hotfix(repo)
        repo.sh("cherry-pick", "-x", "--no-commit", repo.fix)
        (repo.path / "a.txt").write_text("a fixed, and more\n")
        repo.sh("add", "a.txt")
        repo.sh(
            "commit",
            "-q",
            "-m",
            f"security(deps): pin the fix\n\n(cherry picked from commit {repo.fix})",
        )
        _bump(repo)
        with pytest.raises(SourceError, match="patch-id differs"):
            repo.check("hotfix/v1.0.5")

    def test_the_version_must_be_the_next_patch(self, repo: Repo) -> None:
        _cut_hotfix(repo, version="1.0.6")
        repo.sh("cherry-pick", "-x", repo.fix)
        _bump(repo, version="1.0.6")
        with pytest.raises(SourceError, match=r"must be v1\.0\.5"):
            repo.check("hotfix/v1.0.6")

    def test_the_branch_must_be_bumped(self, repo: Repo) -> None:
        _cut_hotfix(repo)
        repo.sh("cherry-pick", "-x", repo.fix)
        with pytest.raises(SourceError, match=r"its version is 1\.0\.4"):
            repo.check("hotfix/v1.0.5")

    def test_a_branch_not_cut_from_the_release_tag_is_refused(self, repo: Repo) -> None:
        _cut_hotfix(repo, base="main")
        _bump(repo)
        with pytest.raises(SourceError, match=r"not cut from v1\.0\.4"):
            repo.check("hotfix/v1.0.5")

    def test_a_bump_that_changes_more_than_the_version_is_refused(self, repo: Repo) -> None:
        _cut_hotfix(repo)
        repo.sh("cherry-pick", "-x", repo.fix)
        _bump(repo, extra='dependencies = ["evil==1"]\n')
        with pytest.raises(SourceError, match="changes more than the version"):
            repo.check("hotfix/v1.0.5")

    def test_an_evil_merge_that_adds_a_file_is_refused(self, repo: Repo) -> None:
        _cut_hotfix(repo)
        repo.sh("switch", "-q", "-c", "hotfix/v1.0.5-fix")
        repo.sh("cherry-pick", "-x", repo.fix)
        repo.sh("switch", "-q", "hotfix/v1.0.5")
        repo.sh("merge", "-q", "--no-ff", "--no-commit", "hotfix/v1.0.5-fix")
        (repo.path / "evil.txt").write_text("x\n")
        repo.sh("add", "evil.txt")
        repo.sh("commit", "-q", "-m", "Merge pull request #9 from x")
        _bump(repo)
        with pytest.raises(SourceError, match=r"beyond its cherry-picks.*evil\.txt"):
            repo.check("hotfix/v1.0.5")

    def test_a_hotfix_with_no_fix_is_refused(self, repo: Repo) -> None:
        _cut_hotfix(repo)
        _bump(repo)
        with pytest.raises(SourceError, match="no cherry-picked fix"):
            repo.check("hotfix/v1.0.5")


@pytest.mark.parametrize("head_ref", ["feat/x", "hotfix/1.0.5", "hotfix/v1.0", "release"])
def test_any_other_head_is_refused(repo: Repo, head_ref: str) -> None:
    repo.sh("branch", "-f", head_ref, "main")
    with pytest.raises(SourceError, match=r"only main or hotfix/vX\.Y\.Z"):
        repo.check(head_ref)


def test_the_bump_allowlist_covers_what_bump_version_rewrote_for_v1_0_5() -> None:
    # The 22 paths `just bump-version 1.0.5` changed on v1.0.4 (2026-10-27).
    rewritten = {
        "CHANGELOG.md", "pyproject.toml", "uv.lock", "apps/syn-docs/openapi.json",
        "apps/syn-api/pyproject.toml", "packages/syn-adapters/pyproject.toml",
        "packages/syn-collector/pyproject.toml", "packages/syn-domain/pyproject.toml",
        "packages/syn-perf/pyproject.toml", "packages/syn-shared/pyproject.toml",
        "packages/syn-tokens/pyproject.toml", "apps/syn-cli-node/package.json",
        "apps/syn-dashboard-ui/package.json", "apps/syn-docs/package.json",
        "apps/syn-ui/package.json", "packages/syn-ui/data/package.json",
        "packages/syn-ui/skyline-core/package.json",
        "packages/syn-ui/skyline-svelte-v5/package.json", "packages/syn-ui/themes/package.json",
        "schemas/plugin/workflow.schema.json", "schemas/plugin/triggers.schema.json",
        "schemas/plugin/phase-frontmatter.schema.json",
    }  # fmt: skip
    assert rewritten <= bump_files()
