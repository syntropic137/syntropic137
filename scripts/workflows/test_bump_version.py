"""Tests for scripts/workflows/bump_version.py.

Covers version comparison, consistency checking, release bump validation,
and the bump logic itself. All tests are pure unit tests - no git or
filesystem side effects beyond temporary directories.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
from bump_version import (
    _parse_semver,
    bump,
    check_consistency,
    check_release_bump,
    compare_versions,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Semver parsing
# =============================================================================


class TestParseSemver:
    def test_stable(self) -> None:
        assert _parse_semver("1.2.3") == (1, 2, 3, None)

    def test_prerelease(self) -> None:
        assert _parse_semver("0.24.2-beta.1") == (0, 24, 2, ["beta", "1"])

    def test_multi_part_prerelease(self) -> None:
        assert _parse_semver("1.0.0-rc.2.3") == (1, 0, 0, ["rc", "2", "3"])

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid semantic version"):
            _parse_semver("not-a-version")

    def test_invalid_missing_patch_raises(self) -> None:
        with pytest.raises(ValueError):
            _parse_semver("1.2")


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


# =============================================================================
# check_consistency
# =============================================================================


def _make_version_files(tmp_path: Path, version: str) -> None:
    """Write all 11 version files at the given version into tmp_path."""
    pyprojects = [
        "pyproject.toml",
        "apps/syn-api/pyproject.toml",
        "packages/syn-adapters/pyproject.toml",
        "packages/syn-collector/pyproject.toml",
        "packages/syn-domain/pyproject.toml",
        "packages/syn-perf/pyproject.toml",
        "packages/syn-shared/pyproject.toml",
        "packages/syn-tokens/pyproject.toml",
    ]
    package_jsons = [
        "apps/syn-cli-node/package.json",
        "apps/syn-dashboard-ui/package.json",
        "apps/syn-docs/package.json",
    ]
    for rel in pyprojects:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            textwrap.dedent(f"""\
            [project]
            name = "placeholder"
            version = "{version}"
        """)
        )
    for rel in package_jsons:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"name": "placeholder", "version": version}, indent=2) + "\n")


def _record_regeneration(
    monkeypatch: pytest.MonkeyPatch, pyproject: Path
) -> list[tuple[list[str], str]]:
    """Stub the derived-artifact generators, recording what each one would have seen.

    Returns (command, pyproject-contents-at-call-time) per invocation. The
    second element is the point: the generators read the version back off
    disk, so it is the only evidence that they ran late enough to see it.
    """
    import bump_version as bv

    calls: list[tuple[list[str], str]] = []

    def fake_run(
        cmd: list[str],
        *,
        cwd: Path | None = None,
        capture_output: bool = False,
        text: bool = False,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, pyproject.read_text()))
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(bv.subprocess, "run", fake_run)
    return calls


class TestCheckConsistency:
    def test_all_match(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_version_files(tmp_path, "0.24.2")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)
        monkeypatch.setattr(
            bv,
            "PYPROJECT_FILES",
            [
                tmp_path / p
                for p in [
                    "pyproject.toml",
                    "apps/syn-api/pyproject.toml",
                    "packages/syn-adapters/pyproject.toml",
                    "packages/syn-collector/pyproject.toml",
                    "packages/syn-domain/pyproject.toml",
                    "packages/syn-perf/pyproject.toml",
                    "packages/syn-shared/pyproject.toml",
                    "packages/syn-tokens/pyproject.toml",
                ]
            ],
        )
        monkeypatch.setattr(
            bv,
            "PACKAGE_JSON_FILES",
            [
                tmp_path / p
                for p in [
                    "apps/syn-cli-node/package.json",
                    "apps/syn-dashboard-ui/package.json",
                    "apps/syn-docs/package.json",
                ]
            ],
        )
        assert check_consistency() is True

    def test_mismatch_detected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_version_files(tmp_path, "0.24.2")
        # Introduce a mismatch in one package.json
        bad = tmp_path / "apps/syn-cli-node/package.json"
        bad.write_text(json.dumps({"name": "placeholder", "version": "0.24.1"}))

        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)
        monkeypatch.setattr(
            bv,
            "PYPROJECT_FILES",
            [tmp_path / "pyproject.toml"],
        )
        monkeypatch.setattr(
            bv,
            "PACKAGE_JSON_FILES",
            [tmp_path / "apps/syn-cli-node/package.json"],
        )
        assert check_consistency() is False


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
        _make_version_files(tmp_path, "0.24.3")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)
        self._mock_git_show(monkeypatch, "0.24.2")
        assert check_release_bump() is True

    def test_same_version_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_version_files(tmp_path, "0.24.2")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)
        self._mock_git_show(monkeypatch, "0.24.2")
        assert check_release_bump() is False

    def test_lower_version_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_version_files(tmp_path, "0.24.1")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)
        self._mock_git_show(monkeypatch, "0.24.2")
        assert check_release_bump() is False

    def test_prerelease_before_stable_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 0.24.2-beta.1 < 0.24.2 - should fail
        _make_version_files(tmp_path, "0.24.2-beta.1")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)
        self._mock_git_show(monkeypatch, "0.24.2")
        assert check_release_bump() is False

    def test_git_failure_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_version_files(tmp_path, "0.24.3")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)

        def fail_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            raise subprocess.CalledProcessError(1, "git")

        monkeypatch.setattr(bv.subprocess, "run", fail_run)
        assert check_release_bump() is False


# =============================================================================
# bump - filesystem round-trip
# =============================================================================


class TestBump:
    def test_updates_all_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_version_files(tmp_path, "0.24.2")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)
        monkeypatch.setattr(
            bv,
            "PYPROJECT_FILES",
            [tmp_path / "pyproject.toml"],
        )
        monkeypatch.setattr(
            bv,
            "PACKAGE_JSON_FILES",
            [tmp_path / "apps/syn-cli-node/package.json"],
        )
        _record_regeneration(monkeypatch, tmp_path / "pyproject.toml")

        bump("0.25.0")

        pyproject = (tmp_path / "pyproject.toml").read_text()
        assert 'version = "0.25.0"' in pyproject

        pkg = json.loads((tmp_path / "apps/syn-cli-node/package.json").read_text())
        assert pkg["version"] == "0.25.0"

    def test_noop_if_already_at_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _make_version_files(tmp_path, "0.24.2")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)
        monkeypatch.setattr(bv, "PYPROJECT_FILES", [tmp_path / "pyproject.toml"])
        monkeypatch.setattr(bv, "PACKAGE_JSON_FILES", [])

        bump("0.24.2")
        out = capsys.readouterr().out
        assert "nothing to do" in out

    def test_invalid_version_exits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_version_files(tmp_path, "0.24.2")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)

        with pytest.raises(SystemExit):
            bump("not-a-version")


# =============================================================================
# Derived artifacts - the version is generated INTO these, not edited in them
# =============================================================================


class TestRegenerateDerivedArtifacts:
    """A bump that leaves generated artifacts stale is a half-finished bump (#1091).

    These assert on what CONSUMES the version - the generators - rather than on
    the eleven files the bump obviously rewrites.
    """

    def _bump_in(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_version_files(tmp_path, "0.24.2")
        import bump_version as bv

        monkeypatch.setattr(bv, "ROOT", tmp_path)
        monkeypatch.setattr(bv, "PYPROJECT_FILES", [tmp_path / "pyproject.toml"])
        monkeypatch.setattr(bv, "PACKAGE_JSON_FILES", [])

    def test_every_registered_artifact_is_regenerated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bump_version as bv

        self._bump_in(tmp_path, monkeypatch)
        calls = _record_regeneration(monkeypatch, tmp_path / "pyproject.toml")

        bump("0.25.0")

        assert [cmd for cmd, _ in calls] == [cmd for _, cmd in bv.DERIVED_ARTIFACTS]

    def test_generators_see_the_new_version_on_disk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ordering hop: generators read the version back off disk.

        Regenerating before the write re-stamps 0.24.2 and leaves the tree
        exactly as stale as it was - which no assertion on the eleven version
        files would ever notice.
        """
        self._bump_in(tmp_path, monkeypatch)
        calls = _record_regeneration(monkeypatch, tmp_path / "pyproject.toml")

        bump("0.25.0")

        assert calls, "bump regenerated nothing - derived artifacts left stale"
        for cmd, pyproject_at_call_time in calls:
            assert 'version = "0.25.0"' in pyproject_at_call_time, (
                f"{cmd} ran before the version was written; it re-stamped the old version"
            )

    def test_failed_generator_fails_the_bump_with_an_instruction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A generator that cannot run must not be reported as a clean bump."""
        import bump_version as bv

        self._bump_in(tmp_path, monkeypatch)

        def failing_run(
            cmd: list[str],
            *,
            cwd: Path | None = None,
            capture_output: bool = False,
            text: bool = False,
            check: bool = False,
        ) -> subprocess.CompletedProcess[str]:
            raise subprocess.CalledProcessError(1, cmd, stderr="boom")

        monkeypatch.setattr(bv.subprocess, "run", failing_run)

        with pytest.raises(SystemExit) as exc:
            bump("0.25.0")

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "just codegen" in err

    def test_registry_covers_the_lockfile_and_the_plugin_schemas(self) -> None:
        """Both artifacts measured stale after a real bump must stay covered.

        uv.lock is the one the issue did not name; it is only caught today
        because `uv run` silently re-locks, which is not a guarantee.
        """
        import bump_version as bv

        labels = {label for label, _ in bv.DERIVED_ARTIFACTS}
        assert labels == {"uv.lock", "plugin JSON schemas"}
