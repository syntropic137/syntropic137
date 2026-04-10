"""Tests for scripts/workflows/check_drift.py."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from check_drift import check_drift, _git_diff, _git_untracked

pytestmark = pytest.mark.unit


class TestCheckDrift:
    def _mock_git(
        self,
        monkeypatch: pytest.MonkeyPatch,
        changed: list[str],
        untracked: list[str],
    ) -> None:
        def fake_run(
            cmd: list[str],
            *,
            capture_output: bool = False,
            text: bool = False,
            check: bool = False,
            **kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            if "diff" in cmd and "--name-only" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "\n".join(changed) + "\n")
            if "ls-files" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "\n".join(untracked) + "\n")
            return subprocess.CompletedProcess(cmd, 0, "")

        monkeypatch.setattr(subprocess, "run", fake_run)

    def test_clean_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._mock_git(monkeypatch, changed=[], untracked=[])
        assert check_drift(["apps/syn-cli-node/src/generated/"]) is True

    def test_changed_files_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._mock_git(monkeypatch, changed=["apps/syn-cli-node/src/generated/api-types.ts"], untracked=[])
        assert check_drift(["apps/syn-cli-node/src/generated/"]) is False

    def test_untracked_files_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._mock_git(monkeypatch, changed=[], untracked=["apps/syn-docs/content/docs/cli/new-cmd.md"])
        assert check_drift(["apps/syn-docs/content/docs/cli/"]) is False

    def test_both_changed_and_untracked_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._mock_git(
            monkeypatch,
            changed=["apps/syn-cli-node/src/generated/api-types.ts"],
            untracked=["apps/syn-docs/content/docs/cli/new.md"],
        )
        assert check_drift(["apps/syn-cli-node/src/generated/", "apps/syn-docs/content/docs/cli/"]) is False

    def test_multiple_paths_all_clean(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._mock_git(monkeypatch, changed=[], untracked=[])
        assert check_drift([
            "apps/syn-cli-node/src/generated/",
            "apps/syn-docs/content/docs/cli/",
            "apps/syn-docs/openapi.json",
        ]) is True
