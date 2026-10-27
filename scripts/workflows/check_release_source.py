#!/usr/bin/env python3
"""Decide whether a pull request into `release` comes from an allowed source.

Two sources may open a PR into `release` (ADR-077):

- `main`: the normal, beta-gated release. Refused while `release` carries a
  non-merge commit that `main` does not, because that is a hotfix nobody
  forward-merged, and releasing over it would silently drop the fix.
- `hotfix/vX.Y.Z`: a hotfix release. It must be cut from the commit the last
  release was tagged on, carry only `git cherry-pick -x` copies of commits
  already on `main` plus one `chore: bump version to vX.Y.Z` commit, and be
  exactly one patch above the release it fixes. The branch's tree must equal
  "the release, plus those cherry-picks, plus the version bump": anything else
  (an extra edit, a hand-resolved conflict that changed more than versions, an
  evil merge) fails.

Every other head branch is refused, and so is any head pushed from another
repository: a fork's branch named `main` is not `main`.

The checker never executes the candidate. CI runs the copy on the `release`
branch (`pull_request_target`) and reads the head only as git objects.

CI DEPENDENCY - called by .github/workflows/release-source.yml:
    uv run --no-project python scripts/workflows/check_release_source.py \\
        --head-ref <head branch> --head-repo <owner/repo> --base-repo <owner/repo> \\
        --head-sha <sha> --base-sha <release sha>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bump_version import (
    lockfile,
    owned_packages,
    package_json_files,
    schema_files,
)

ROOT: Final = Path(__file__).resolve().parents[2]
MAIN_HEAD: Final = "main"
MAIN_REF: Final = "origin/main"
HOTFIX_BRANCH_RE: Final = re.compile(r"^hotfix/v(\d+)\.(\d+)\.(\d+)$")
CHERRY_PICK_RE: Final = re.compile(r"^\(cherry picked from commit ([0-9a-f]{40})\)$", re.MULTILINE)
PYPROJECT_VERSION_RE: Final = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
STABLE_VERSION_RE: Final = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
CHANGELOG: Final = "CHANGELOG.md"
#: Rewritten by `just bump-version` beyond the version-carrying manifests: the
#: changelog section and the OpenAPI spec, whose info.version is the package's.
BUMP_EXTRA_FILES: Final = (CHANGELOG, "apps/syn-docs/openapi.json")
#: The one mode a bumped file may have, before and after.
REGULAR_FILE: Final = "100644"
#: A line `just bump-version` rewrites: a version field and nothing else.
VERSION_LINE_RE: Final = re.compile(
    r'^\s*(version\s*=\s*"[^"]*"|"version"\s*:\s*"[^"]*",?|"\$id"\s*:\s*"[^"]*",?)\s*$'
)
#: Where each kind of bumped file keeps its version, as a key path.
VERSION_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "pyproject.toml": ("project", "version"),
    "package.json": ("version",),
    "openapi.json": ("info", "version"),
    ".schema.json": ("$id",),
}
LOCKFILE_NAME: Final = "uv.lock"

type Key = tuple[str | int, ...]


class SourceError(Exception):
    """The PR's head is not an allowed source for a release."""


@dataclass(frozen=True)
class Git:
    repo: Path

    def run(self, *args: str, env: dict[str, str] | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env={**os.environ, **env} if env else None,
        )
        if result.returncode != 0:
            raise SourceError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout

    def ok(self, *args: str) -> bool:
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True).returncode == 0

    def lines(self, *args: str) -> list[str]:
        return [line for line in self.run(*args).splitlines() if line]

    def patch_id(self, sha: str) -> str:
        diff = self.run("show", "--format=", "--no-color", sha)
        result = subprocess.run(
            ["git", "patch-id", "--stable"],
            cwd=self.repo,
            input=diff,
            capture_output=True,
            text=True,
        )
        return result.stdout.split(" ", 1)[0]

    def version_at(self, sha: str) -> str:
        match = PYPROJECT_VERSION_RE.search(self.run("show", f"{sha}:pyproject.toml"))
        if match is None:
            raise SourceError(f"no version in {sha}:pyproject.toml")
        return match.group(1)


def bump_files() -> frozenset[str]:
    """Every path `just bump-version` is allowed to rewrite, relative to the root."""
    paths = [p.pyproject for p in owned_packages()]
    paths += [*package_json_files(), *schema_files(), lockfile()]
    return frozenset(p.relative_to(ROOT).as_posix() for p in paths) | frozenset(BUMP_EXTRA_FILES)


def check_main(git: Git, head_sha: str, base_sha: str, main_ref: str = MAIN_REF) -> list[str]:
    if not git.ok("merge-base", "--is-ancestor", head_sha, main_ref):
        raise SourceError(f"head {head_sha[:12]} is not on {main_ref}")
    missing = git.lines("rev-list", "--no-merges", f"{head_sha}..{base_sha}")
    if missing:
        raise SourceError(
            f"release carries {len(missing)} commit(s) main does not, e.g. {missing[0][:12]}: "
            "a hotfix was not forward-merged. Merge its hotfix/vX.Y.Z branch into main first"
        )
    return [f"head {head_sha[:12]} is on {main_ref}", "main carries every commit on release"]


def next_patch(version: str) -> str:
    match = STABLE_VERSION_RE.match(version)
    if match is None:
        raise SourceError(f"release is at {version!r}, not a stable X.Y.Z version")
    major, minor, patch = (int(g) for g in match.groups())
    return f"{major}.{minor}.{patch + 1}"


def check_hotfix(
    git: Git,
    branch_version: str,
    head_sha: str,
    base_sha: str,
    allowed: frozenset[str],
    main_ref: str = MAIN_REF,
) -> list[str]:
    notes: list[str] = []
    release_version = git.version_at(base_sha)
    tag = f"v{release_version}"
    if not git.ok("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"):
        raise SourceError(f"release is at {release_version} but tag {tag} does not exist")
    tagged = git.run("rev-parse", f"{tag}^{{commit}}").strip()
    if tagged != base_sha:
        raise SourceError(f"release head {base_sha[:12]} is not the {tag} commit {tagged[:12]}")
    if git.run("merge-base", head_sha, base_sha).strip() != base_sha:
        raise SourceError(f"the branch is not cut from {tag}: cut it with git switch -c ... {tag}")
    notes.append(f"cut from {tag} ({base_sha[:12]}), the latest release")

    expected = next_patch(release_version)
    if branch_version != expected:
        raise SourceError(
            f"a hotfix of {tag} must be v{expected}, the branch says v{branch_version}"
        )
    head_version = git.version_at(head_sha)
    if head_version != branch_version:
        raise SourceError(
            f"the branch is hotfix/v{branch_version} but its version is {head_version}"
        )
    notes.append(f"version {release_version} -> {head_version}")

    sources: list[str] = []
    bumps: list[str] = []
    bump_subject = f"chore: bump version to v{head_version}"
    for sha in git.lines("rev-list", "--no-merges", "--reverse", f"{base_sha}..{head_sha}"):
        message = git.run("log", "-1", "--format=%B", sha)
        picked = CHERRY_PICK_RE.findall(message)
        if picked:
            source = picked[-1]
            if not git.ok("merge-base", "--is-ancestor", source, main_ref):
                raise SourceError(
                    f"{sha[:12]} is cherry-picked from {source[:12]}, which is not on main"
                )
            if len(git.run("rev-list", "--parents", "-1", source).split()) != 2:
                raise SourceError(f"{sha[:12]} is cherry-picked from {source[:12]}, a merge commit")
            if git.patch_id(source) != git.patch_id(sha):
                raise SourceError(
                    f"{sha[:12]} does not carry the same change as {source[:12]} (patch-id differs)"
                )
            sources.append(source)
            notes.append(f"{sha[:12]} = main {source[:12]} {message.splitlines()[0]}")
        elif message.splitlines()[0] == bump_subject:
            bumps.append(sha)
        else:
            raise SourceError(
                f"{sha[:12]} {message.splitlines()[0]!r} is neither a git cherry-pick -x of a "
                f"main commit nor {bump_subject!r}"
            )
    if not sources:
        raise SourceError("the hotfix carries no cherry-picked fix")
    if len(bumps) != 1:
        raise SourceError(f"expected one {bump_subject!r} commit, found {len(bumps)}")

    expected_sha = replay(git, base_sha, sources)
    check_only_version_bumped(git, expected_sha, head_sha, allowed, release_version, head_version)
    notes.append(f"tree = {tag} + {len(sources)} cherry-pick(s) + version bump")
    return notes


def replay(git: Git, base_sha: str, sources: list[str]) -> str:
    """The commit `base + every cherry-pick`, built in a scratch worktree."""
    identity = {
        "GIT_AUTHOR_NAME": "release-source",
        "GIT_AUTHOR_EMAIL": "release-source@invalid",
        "GIT_COMMITTER_NAME": "release-source",
        "GIT_COMMITTER_EMAIL": "release-source@invalid",
    }
    with tempfile.TemporaryDirectory() as scratch:
        tree = Path(scratch) / "expected"
        git.run("worktree", "add", "--detach", str(tree), base_sha)
        try:
            picker = Git(tree)
            for source in sources:
                picker.run(
                    "cherry-pick", "--allow-empty", "--keep-redundant-commits", source, env=identity
                )
            return picker.run("rev-parse", "HEAD").strip()
        except SourceError as err:
            raise SourceError(
                f"the cherry-picks do not apply cleanly to {base_sha[:12]}: {err}"
            ) from err
        finally:
            git.run("worktree", "remove", "--force", str(tree))


def check_only_version_bumped(
    git: Git, expected: str, head_sha: str, allowed: frozenset[str], old: str, new: str
) -> None:
    """The head differs from `expected` only by `just bump-version`'s substitutions.

    Every changed file must be a bumped file, modified in place as a regular
    file. Outside the changelog, every changed line must be a version field
    whose only edit is `old` -> `new`, and the parsed document must be equal
    except at that file kind's version field: a lifecycle script, a dependency
    pin or a duplicate key that happens to contain the version still fails.
    """
    for entry in git.lines("diff", "--raw", "--no-renames", expected, head_sha):
        meta, path = entry.split("\t", 1)
        old_mode, new_mode, _, _, status = meta.lstrip(":").split(" ")
        if path not in allowed:
            raise SourceError(
                f"the branch changes files beyond its cherry-picks and the version bump: {path}"
            )
        if status != "M" or old_mode != REGULAR_FILE or new_mode != REGULAR_FILE:
            raise SourceError(f"{path} must stay a regular file modified in place ({entry})")
        if path == CHANGELOG:
            continue
        for before, after in changed_line_pairs(git, expected, head_sha, path):
            if (
                not VERSION_LINE_RE.match(before)
                or after != before.replace(old, new)
                or old not in before
            ):
                raise SourceError(f"{path} changes more than the version: {after.strip()!r}")
        check_document(
            path,
            git.run("show", f"{expected}:{path}"),
            git.run("show", f"{head_sha}:{path}"),
            old,
            new,
        )


def changed_line_pairs(git: Git, a: str, b: str, path: str) -> list[tuple[str, str]]:
    """Removed and added lines of each `-U0` hunk, paired in order."""
    pairs: list[tuple[str, str]] = []
    removed: list[str] = []
    added: list[str] = []

    def flush() -> None:
        if len(removed) != len(added):
            raise SourceError(f"{path} adds or removes lines; a version bump only rewrites them")
        pairs.extend(zip(removed, added, strict=True))
        removed.clear()
        added.clear()

    for line in git.run("diff", "--no-color", "-U0", a, b, "--", path).splitlines():
        if line.startswith("@@"):
            flush()
        elif line.startswith(("+++", "---", "diff ", "index ")):
            continue
        elif line.startswith("-"):
            removed.append(line[1:])
        elif line.startswith("+"):
            added.append(line[1:])
    flush()
    return pairs


def check_document(path: str, before: str, after: str, old: str, new: str) -> None:
    name = path.rsplit("/", 1)[-1]
    if name == LOCKFILE_NAME:
        a, b = tomllib.loads(before), tomllib.loads(after)
        permitted = {
            ("package", i, "version")
            for i, package in enumerate(a.get("package", []))
            if isinstance(package.get("source"), dict)
            and {"editable", "virtual"} & set(package["source"])
        }
    else:
        field = next((f for suffix, f in VERSION_FIELDS.items() if name.endswith(suffix)), None)
        if field is None:
            raise SourceError(f"{path} is not a file kind `just bump-version` rewrites")
        loads = tomllib.loads if name.endswith(".toml") else json.loads
        a, b = loads(before), loads(after)
        permitted = {field}
    for key, was, now in differences(a, b, ()):
        if key not in permitted:
            raise SourceError(
                f"{path} changes {'.'.join(map(str, key)) or 'its shape'}, not only the version"
            )
        if not (
            isinstance(was, str)
            and isinstance(now, str)
            and old in was
            and now == was.replace(old, new)
        ):
            raise SourceError(f"{path} {'.'.join(map(str, key))} is not a {old} -> {new} rewrite")


def differences(a: object, b: object, key: Key) -> list[tuple[Key, object, object]]:
    """Every leaf where two parsed documents differ, by key path."""
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return [(key, sorted(a), sorted(b))]
        return [d for k in a for d in differences(a[k], b[k], (*key, k))]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [(key, len(a), len(b))]
        return [
            d
            for i, (x, y) in enumerate(zip(a, b, strict=True))
            for d in differences(x, y, (*key, i))
        ]
    return [] if a == b and type(a) is type(b) else [(key, a, b)]


def check_source(
    git: Git,
    head_ref: str,
    head_repo: str,
    base_repo: str,
    head_sha: str,
    base_sha: str,
    allowed: frozenset[str],
    main_ref: str = MAIN_REF,
) -> list[str]:
    if head_repo != base_repo:
        raise SourceError(
            f"the head is in {head_repo}, not {base_repo}: release PRs come from {base_repo} only"
        )
    if head_ref == MAIN_HEAD:
        return check_main(git, head_sha, base_sha, main_ref)
    match = HOTFIX_BRANCH_RE.match(head_ref)
    if match is None:
        raise SourceError(
            f"{head_ref!r} may not open a PR into release: only main or hotfix/vX.Y.Z"
        )
    return check_hotfix(git, ".".join(match.groups()), head_sha, base_sha, allowed, main_ref)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--head-repo", required=True)
    parser.add_argument("--base-repo", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    try:
        notes = check_source(
            Git(ROOT),
            args.head_ref,
            args.head_repo,
            args.base_repo,
            args.head_sha,
            args.base_sha,
            bump_files(),
        )
    except SourceError as err:
        print(f"::error::release source: {err}")
        return 1
    for note in notes:
        print(f"OK: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
