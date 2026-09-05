"""Tests for scripts/workflows/bump_version.py.

Covers the accepted version grammar, version comparison, consistency checking,
release bump validation, and the bump logic itself.

Two things here are deliberately not mocked:

* `_make_repo` builds a *real* uv workspace in tmp_path, so `uv lock` can be
  run against it. `just bump-version` writes the manifests, regenerates
  uv.lock, then runs `--check`; a test that fakes uv.lock cannot see the two
  halves disagree, which is exactly the defect these tests exist to pin.
* the version-to-PEP-440 expectations are confirmed against real `uv lock`
  output rather than against the implementation's own idea of the answer.

Nothing writes outside tmp_path: every path in bump_version resolves against
`ROOT` at call time, and every test that touches the filesystem monkeypatches
it. `uv lock` runs `--offline` and the fixtures have no dependencies.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from bump_version import (
    ROOT,
    bump,
    check_consistency,
    check_release_bump,
    compare_versions,
    owned_packages,
    parse_version,
    read_lockfile_records,
    read_pyproject_version,
    to_pep440,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

pytestmark = pytest.mark.unit


# =============================================================================
# Version grammar
# =============================================================================


class TestParseVersion:
    def test_stable(self) -> None:
        assert parse_version("1.2.3") == (1, 2, 3, None)

    @pytest.mark.parametrize("tag", ["alpha", "beta", "rc"])
    def test_prerelease(self, tag: str) -> None:
        assert parse_version(f"0.24.2-{tag}.1") == (0, 24, 2, (tag, 1))

    def test_multi_digit_prerelease_number(self) -> None:
        assert parse_version("0.24.2-beta.10") == (0, 24, 2, ("beta", 10))

    def test_multi_part_prerelease_rejected(self) -> None:
        """`1.0.0-rc.2.3` used to parse as ("rc", "2", "3"). It no longer does.

        The grammar narrowed from arbitrary SemVer to the forms this repo
        actually ships, because `just bump-version` now regenerates uv.lock and
        re-runs `--check`: a version uv canonicalises differently from
        `to_pep440` is accepted and then immediately reported stale, with no
        way out but to hand-edit the lockfile. uv 0.11.8 does not merely
        rewrite this one - it refuses to parse a manifest containing it.
        See TestToPep440.
        """
        with pytest.raises(ValueError, match="Unsupported version"):
            parse_version("1.0.0-rc.2.3")

    @pytest.mark.parametrize(
        "version",
        [
            "not-a-version",
            "1.2",  # missing patch
            "0.29.0-beta.09",  # zero-padded: uv drops the padding
            "0.29.0-beta1",  # no separator: uv accepts, we do not
            "0.29.0-alpha",  # no number: uv implies 0
            "0.29.0-dev.1",  # different release segment entirely
            "0.29.0-rc.1.2",  # uv cannot parse a manifest with this
            "0.29.0-gamma.1",  # not a tag we ship
            "01.2.3",  # leading zero in the core version
        ],
    )
    def test_rejected(self, version: str) -> None:
        with pytest.raises(ValueError, match="Unsupported version"):
            parse_version(version)


# =============================================================================
# to_pep440 - the mapping uv.lock is checked against
# =============================================================================

# Every branch of the accepted grammar, and what uv 0.11.8 writes for it.
# `test_matches_real_uv` re-derives the right-hand column by running uv, so
# this table cannot quietly drift away from the tool it is modelling.
PEP440_CASES = [
    ("0.29.0", "0.29.0"),
    ("0.29.0-alpha.1", "0.29.0a1"),
    ("0.29.0-beta.9", "0.29.0b9"),
    ("0.29.0-rc.2", "0.29.0rc2"),
    ("0.29.0-beta.0", "0.29.0b0"),
    ("0.29.0-rc.10", "0.29.0rc10"),
]

_UV = shutil.which("uv")
requires_uv = pytest.mark.skipif(_UV is None, reason="uv is not on PATH")


def _uv_lock(project: Path) -> subprocess.CompletedProcess[str]:
    """Run `uv lock` in `project`, offline, with caches confined to it."""
    env = {
        **os.environ,
        "UV_CACHE_DIR": str(project / ".uv-cache"),
        "TMPDIR": str(project / ".tmp"),
    }
    (project / ".tmp").mkdir(exist_ok=True)
    return subprocess.run(
        [_UV or "uv", "lock", "--offline"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class TestToPep440:
    @pytest.mark.parametrize(("version", "expected"), PEP440_CASES)
    def test_table(self, version: str, expected: str) -> None:
        assert to_pep440(version) == expected

    @requires_uv
    @pytest.mark.parametrize(("version", "expected"), PEP440_CASES)
    def test_matches_real_uv(self, version: str, expected: str, tmp_path: Path) -> None:
        """The expectation is uv's, not ours.

        `to_pep440` is a hand-rolled normalisation. The blocker this pins is
        that it can be *plausible* and still disagree with the tool that
        actually writes uv.lock, in which case `--check` calls a correctly
        regenerated lockfile stale.
        """
        (tmp_path / "pyproject.toml").write_text(
            textwrap.dedent(f"""\
                [project]
                name = "probe"
                version = "{version}"
                requires-python = ">=3.12"
                dependencies = []
            """)
        )
        result = _uv_lock(tmp_path)
        assert result.returncode == 0, result.stderr
        lock = (tmp_path / "uv.lock").read_text()
        assert f'version = "{expected}"' in lock, lock
        assert to_pep440(version) == expected

    def test_rejects_what_the_grammar_rejects(self) -> None:
        with pytest.raises(ValueError, match="Unsupported version"):
            to_pep440("0.29.0-dev.1")


# =============================================================================
# Version comparison
# =============================================================================


class TestCompareVersions:
    # Stable ordering
    def test_patch_increment(self) -> None:
        assert compare_versions("0.24.3", "0.24.2") == 1

    def test_minor_increment(self) -> None:
        assert compare_versions("0.25.0", "0.24.9") == 1

    def test_major_increment(self) -> None:
        assert compare_versions("1.0.0", "0.99.99") == 1

    def test_equal(self) -> None:
        assert compare_versions("0.24.2", "0.24.2") == 0

    def test_less_than(self) -> None:
        assert compare_versions("0.24.1", "0.24.2") == -1

    # Prerelease ordering (semver spec: stable > prerelease of same core)
    def test_stable_greater_than_prerelease(self) -> None:
        assert compare_versions("0.24.2", "0.24.2-beta.1") == 1

    def test_prerelease_less_than_stable(self) -> None:
        assert compare_versions("0.24.2-beta.1", "0.24.2") == -1

    def test_prerelease_numeric_ordering(self) -> None:
        assert compare_versions("0.24.2-beta.2", "0.24.2-beta.1") == 1
        assert compare_versions("0.24.2-beta.10", "0.24.2-beta.9") == 1

    def test_prerelease_alpha_before_beta(self) -> None:
        assert compare_versions("0.24.2-alpha.1", "0.24.2-beta.1") == -1

    def test_rc_after_beta(self) -> None:
        assert compare_versions("0.24.2-rc.1", "0.24.2-beta.1") == 1

    def test_two_prereleases_equal(self) -> None:
        assert compare_versions("0.24.2-beta.1", "0.24.2-beta.1") == 0

    def test_unsupported_version_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported version"):
            compare_versions("0.24.2-dev.1", "0.24.2")


# =============================================================================
# A real uv workspace, in tmp_path
# =============================================================================

_MEMBER_DIRS = (
    "apps/syn-api",
    "packages/syn-adapters",
    "packages/syn-collector",
    "packages/syn-domain",
    "packages/syn-perf",
    "packages/syn-shared",
    "packages/syn-tokens",
)

_NODE_MANIFESTS = (
    "apps/syn-cli-node/package.json",
    "apps/syn-dashboard-ui/package.json",
    "apps/syn-docs/package.json",
)

_SCHEMAS = (
    "schemas/plugin/workflow.schema.json",
    "schemas/plugin/triggers.schema.json",
    "schemas/plugin/phase-frontmatter.schema.json",
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _make_repo(tmp_path: Path, version: str, extra_members: Iterable[str] = ()) -> None:
    """Write a working miniature of this repo at `version` into tmp_path.

    A real uv workspace: the same members/exclude globs, an excluded Node app
    and an excluded independently-versioned package, the three plugin schemas.
    `uv lock` runs against it, so nothing about uv's behaviour is simulated.
    """
    _write(
        tmp_path / "pyproject.toml",
        textwrap.dedent(f"""\
            [project]
            name = "syntropic137"
            version = "{version}"
            requires-python = ">=3.12"
            dependencies = []

            [tool.uv.workspace]
            members = ["apps/*", "packages/*"]
            exclude = [
                "apps/syn-cli-node",
                "apps/syn-dashboard-ui",
                "apps/syn-docs",
                "packages/openclaw-plugin",
            ]
        """),
    )
    for rel in (*_MEMBER_DIRS, *extra_members):
        _write(
            tmp_path / rel / "pyproject.toml",
            textwrap.dedent(f"""\
                [project]
                name = "{Path(rel).name}"
                version = "{version}"
                requires-python = ">=3.12"
                dependencies = []
            """),
        )
    for rel in _NODE_MANIFESTS:
        _write(tmp_path / rel, json.dumps({"name": "placeholder", "version": version}, indent=2))
    # Excluded from the workspace and independently versioned - a bump must
    # leave it alone, and `--check` must not demand it match.
    _write(
        tmp_path / "packages/openclaw-plugin/package.json",
        json.dumps({"name": "openclaw-plugin", "version": "0.1.0"}, indent=2),
    )
    for rel in _SCHEMAS:
        _write(
            tmp_path / rel,
            '{\n  "$id": "https://syntropic137.dev/schemas/plugin/v'
            + version
            + '/x.schema.json"\n}\n',
        )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A miniature repo at 0.28.0 with bump_version pointed at it.

    ROOT is the only knob: every path the script uses is derived from it at
    call time. An earlier revision had module-level absolute paths and `bump()`
    escaped into the real checkout during tests.
    """
    import bump_version as bv

    _make_repo(tmp_path, "0.28.0")
    monkeypatch.setattr(bv, "ROOT", tmp_path)
    return tmp_path


def _relock(project: Path) -> None:
    result = _uv_lock(project)
    assert result.returncode == 0, result.stderr


# =============================================================================
# The full `just bump-version` sequence: bump -> uv lock -> --check
# =============================================================================


@requires_uv
class TestBumpThenLockThenCheck:
    """`just bump-version` writes manifests, runs `uv lock`, then `--check`.

    Any accepted version whose PEP 440 spelling this script gets wrong is
    reported stale the instant it is used, and the only escape is hand-editing
    a file uv owns. So the assertion is the whole sequence, per grammar branch,
    against real uv - not that each half agrees with itself.
    """

    @pytest.mark.parametrize("target", [v for v, _ in PEP440_CASES])
    def test_check_passes_after_bump_and_relock(self, repo: Path, target: str) -> None:
        bump(target)
        _relock(repo)
        assert check_consistency() is True

    def test_check_fails_if_the_lock_is_not_regenerated(self, repo: Path) -> None:
        _relock(repo)
        bump("0.29.0-beta.1")
        assert check_consistency() is False

    def test_a_new_workspace_member_is_bumped_and_checked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ninth package. Nothing in this script names it.

        Membership used to be a hand-written tuple: a package added here landed
        in uv.lock automatically and in `--check` never. Deriving it from
        `[tool.uv.workspace]` is what makes this pass with no edit.
        """
        import bump_version as bv

        _make_repo(tmp_path, "0.28.0", extra_members=["packages/syn-ninth"])
        monkeypatch.setattr(bv, "ROOT", tmp_path)

        bump("0.29.0")
        _relock(tmp_path)

        assert 'version = "0.29.0"' in (tmp_path / "packages/syn-ninth/pyproject.toml").read_text()
        assert check_consistency() is True

        # ...and it is genuinely covered, not merely present: corrupt only its
        # lock record and `--check` must object.
        lock = tmp_path / "uv.lock"
        lock.write_text(
            lock.read_text().replace(
                'name = "syn-ninth"\nversion = "0.29.0"',
                'name = "syn-ninth"\nversion = "0.28.0"',
            )
        )
        assert check_consistency() is False


@requires_uv
class TestEveryOwnedPackageIsChecked:
    """Corrupting any single owned package's lock record must be caught.

    Parameterised over the workspace as uv resolves it, so a package that the
    derivation drops fails here by name rather than silently reducing coverage.
    """

    @pytest.mark.parametrize("relpath", [".", *_MEMBER_DIRS])
    def test_stale_lock_record_for(
        self, repo: Path, relpath: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _relock(repo)
        assert check_consistency() is True
        capsys.readouterr()

        records = read_lockfile_records()
        assert relpath in records, f"uv did not record {relpath}; fixture is wrong"
        name = records[relpath].name

        lock = repo / "uv.lock"
        lock.write_text(
            lock.read_text().replace(
                f'name = "{name}"\nversion = "0.28.0"',
                f'name = "{name}"\nversion = "0.27.0"',
            )
        )
        assert check_consistency() is False
        assert name in capsys.readouterr().err

    def test_missing_lock_record_is_reported(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _relock(repo)
        lock = repo / "uv.lock"
        blocks = lock.read_text().split("[[package]]")
        lock.write_text("[[package]]".join(b for b in blocks if 'name = "syn-tokens"' not in b))

        assert check_consistency() is False
        assert "packages/syn-tokens" in capsys.readouterr().err


# =============================================================================
# Workspace membership is derived, and it matches this repo
# =============================================================================


class TestOwnedPackagesMatchesThisRepo:
    """Cross-checks the derivation against uv's own record of the workspace.

    `owned_packages()` reads the members/exclude globs; uv.lock is written by
    uv from the same config. Two independent derivations that must agree - so
    excluding a package, or adding one uv does not know about, fails here.
    """

    def _lock_workspace_paths(self) -> set[str]:
        # Submodules are vendored under lib/ and version independently. That is
        # the only distinction between a workspace record we own and one we do
        # not, and it is stated once, here.
        return {p for p in read_lockfile_records() if not p.startswith("lib/")}

    def test_derivation_matches_uv_lock(self) -> None:
        assert {p.relpath for p in owned_packages()} == self._lock_workspace_paths()

    def test_the_submodules_are_excluded(self) -> None:
        owned = {p.relpath for p in owned_packages()}
        assert owned.isdisjoint(
            {p for p in read_lockfile_records() if p.startswith("lib/")},
        )
        assert len(read_lockfile_records()) > len(owned), "expected submodule records in uv.lock"

    def test_every_owned_package_is_at_the_product_version(self) -> None:
        """Ownership means lockstep. A derived member that is not actually
        versioned with the product would make `--check` unsatisfiable."""
        product = read_pyproject_version(ROOT / "pyproject.toml")
        for pkg in owned_packages():
            assert pkg.pyproject.is_file(), pkg.relpath
            assert read_pyproject_version(pkg.pyproject) == product, pkg.relpath


class TestNodeManifestList:
    """The Node manifests have no glob to derive from, so the list is checked."""

    def test_matches_pnpm_workspace(self) -> None:
        """Every pnpm member is either versioned in lockstep or independent.

        Adding an app to pnpm-workspace.yaml and forgetting bump_version is the
        same drift as the uv one; there is no glob to derive this from, so it
        is asserted instead.
        """
        import bump_version as bv

        declared = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text())["packages"]
        # openclaw-plugin ships on its own version (0.1.0), by design.
        independent = {"packages/openclaw-plugin"}
        expected = {f"{d}/package.json" for d in declared if d not in independent}
        assert set(bv.PACKAGE_JSON_RELPATHS) == expected

    def test_the_independent_package_really_is_independent(self) -> None:
        """If openclaw-plugin ever joins the product version, the exemption in
        the test above stops being true and must be removed rather than kept
        as a permanent hole."""
        product = json.loads((ROOT / "apps/syn-cli-node/package.json").read_text())["version"]
        plugin = json.loads((ROOT / "packages/openclaw-plugin/package.json").read_text())["version"]
        assert plugin != product


# =============================================================================
# check_consistency - manifest disagreement
# =============================================================================


@requires_uv
class TestCheckConsistency:
    def test_all_match(self, repo: Path) -> None:
        _relock(repo)
        assert check_consistency() is True

    def test_manifest_mismatch_detected(self, repo: Path) -> None:
        _relock(repo)
        bad = repo / "apps/syn-cli-node/package.json"
        bad.write_text(json.dumps({"name": "placeholder", "version": "0.24.1"}))
        assert check_consistency() is False

    def test_stale_schema_id_fails(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _relock(repo)
        stale = repo / "schemas/plugin/triggers.schema.json"
        stale.write_text(stale.read_text().replace("/v0.28.0/", "/v0.27.0/"))

        assert check_consistency() is False
        assert "triggers.schema.json" in capsys.readouterr().err

    def test_prerelease_lockfile_uses_pep440(self, repo: Path) -> None:
        """uv writes 0.28.0b9, not 0.28.0-beta.9. Comparing semver to the lock
        would report every prerelease bump as stale."""
        bump("0.28.0-beta.9")
        _relock(repo)
        assert "0.28.0b9" in (repo / "uv.lock").read_text()
        assert check_consistency() is True

    def test_unsupported_version_in_pyproject_is_reported(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--check` reads whatever the manifests hold, including a hand-edit
        this script would never have written. It must say so, not crash."""
        _relock(repo)
        for pkg in owned_packages():
            pkg.pyproject.write_text(
                pkg.pyproject.read_text().replace('version = "0.28.0"', 'version = "0.28.0-dev.1"')
            )
        for rel in _NODE_MANIFESTS:
            (repo / rel).write_text(
                json.dumps({"name": "placeholder", "version": "0.28.0-dev.1"}, indent=2)
            )

        assert check_consistency() is False
        assert "Unsupported version" in capsys.readouterr().err


# =============================================================================
# check_release_bump - uses subprocess.run, so mock it
# =============================================================================


class TestCheckReleaseBump:
    def _mock_git_show(self, monkeypatch: pytest.MonkeyPatch, release_version: str) -> None:
        """Patch subprocess.run to return a fake pyproject.toml from the release branch."""
        import bump_version as bv

        pyproject_content = textwrap.dedent(f"""\
            [project]
            version = "{release_version}"
        """)

        def fake_run(
            cmd: list[str],
            *,
            capture_output: bool = False,
            text: bool = False,
            check: bool = False,
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout=pyproject_content)

        monkeypatch.setattr(bv.subprocess, "run", fake_run)

    def test_bumped_version_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_repo(tmp_path, "0.24.3")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)
        self._mock_git_show(monkeypatch, "0.24.2")
        assert check_release_bump() is True

    def test_same_version_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_repo(tmp_path, "0.24.2")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)
        self._mock_git_show(monkeypatch, "0.24.2")
        assert check_release_bump() is False

    def test_lower_version_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_repo(tmp_path, "0.24.1")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)
        self._mock_git_show(monkeypatch, "0.24.2")
        assert check_release_bump() is False

    def test_prerelease_before_stable_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 0.24.2-beta.1 < 0.24.2 - should fail
        _make_repo(tmp_path, "0.24.2-beta.1")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)
        self._mock_git_show(monkeypatch, "0.24.2")
        assert check_release_bump() is False

    def test_git_failure_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_repo(tmp_path, "0.24.3")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)

        def fail_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            raise subprocess.CalledProcessError(1, "git")

        monkeypatch.setattr(bv.subprocess, "run", fail_run)
        assert check_release_bump() is False

    def test_unsupported_release_version_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_repo(tmp_path, "0.24.3")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)
        self._mock_git_show(monkeypatch, "0.24.2-dev.1")
        assert check_release_bump() is False


# =============================================================================
# bump - filesystem round-trip
# =============================================================================


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): p.read_text()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.name.startswith(".")
    }


class TestBump:
    def test_updates_every_owned_manifest_and_schema(self, repo: Path) -> None:
        bump("0.29.0")

        for pkg in owned_packages():
            assert 'version = "0.29.0"' in pkg.pyproject.read_text(), pkg.relpath
        for rel in _NODE_MANIFESTS:
            assert json.loads((repo / rel).read_text())["version"] == "0.29.0"
        for rel in _SCHEMAS:
            assert "/v0.29.0/" in (repo / rel).read_text()

    def test_leaves_the_independently_versioned_package_alone(self, repo: Path) -> None:
        bump("0.29.0")
        plugin = repo / "packages/openclaw-plugin/package.json"
        assert json.loads(plugin.read_text())["version"] == "0.1.0"

    def test_noop_if_already_at_version(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bump("0.28.0")
        assert "nothing to do" in capsys.readouterr().out

    @pytest.mark.parametrize(
        "target",
        [
            "not-a-version",
            "0.29.0-beta.09",
            "0.29.0-beta1",
            "0.29.0-alpha",
            "0.29.0-dev.1",
            "0.29.0-rc.1.2",
        ],
    )
    def test_rejected_version_touches_nothing(self, repo: Path, target: str) -> None:
        """Rejection has to happen before the first write.

        A half-bumped tree is worse than no bump: the manifests disagree with
        each other and with uv.lock, and `--check` cannot tell you which half
        is the intended version.
        """
        before = _snapshot(repo)
        with pytest.raises(SystemExit) as exc:
            bump(target)
        assert exc.value.code == 1
        assert _snapshot(repo) == before

    def test_missing_version_field_touches_nothing(self, repo: Path) -> None:
        (repo / "packages/syn-tokens/pyproject.toml").write_text('[project]\nname = "syn-tokens"\n')
        before = _snapshot(repo)
        with pytest.raises(SystemExit):
            bump("0.29.0")
        assert _snapshot(repo) == before
