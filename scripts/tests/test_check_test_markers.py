"""The marker gate must not produce false positives.

This gate shipped one: it globbed ``test_*.py`` from the repo root, and
``.claude/worktrees/`` holds complete repo copies, so two agent worktrees made
it count the same two xfail markers three times. It failed the build over four
disarmed guards that did not exist.

A false positive is worse than a missed defect. A gate that cries wolf gets
muted, and a muted gate is indistinguishable from no gate - which is the exact
failure this gate was written to catch. So the exclusion behaviour is pinned
here, not left to a reviewer to notice.

The gate was inline in the justfile when it shipped that bug, which is why it
had no test. Being untestable was the root cause; these tests exist because it
is now a module.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_test_markers import (  # noqa: E402
    Budget,
    count_xfail_markers,
    evaluate,
    is_excluded,
    iter_test_files,
    parse_collected,
)


@pytest.mark.unit
class TestWorktreesAreExcluded:
    """The exact false positive that shipped."""

    def test_agent_worktree_is_excluded(self) -> None:
        assert is_excluded(".claude/worktrees/agent-abc123/packages/x/test_thing.py")

    def test_first_party_test_is_not_excluded(self) -> None:
        assert not is_excluded("packages/syn-adapters/tests/test_manager_event_routing.py")

    @pytest.mark.parametrize(
        "path",
        [
            ".venv/lib/python3.14/site-packages/pkg/test_x.py",
            "apps/syn-cli-node/node_modules/dep/test_y.py",
            "some/site-packages/test_z.py",
        ],
    )
    def test_vendored_trees_are_excluded(self, path: str) -> None:
        assert is_excluded(path)

    def test_duplicate_copies_are_counted_once(self, tmp_path: Path) -> None:
        """Two worktree copies of one file must not treble the count.

        This is the regression, reproduced exactly: the same marker in the real
        tree and in two agent worktrees previously counted as three.
        """
        body = "import pytest\n\n\n@pytest.mark.xfail(reason='x')\ndef test_a():\n    pass\n"

        real = tmp_path / "packages" / "tests"
        real.mkdir(parents=True)
        (real / "test_thing.py").write_text(body)

        for agent in ("agent-aaa", "agent-bbb"):
            copy = tmp_path / ".claude" / "worktrees" / agent / "packages" / "tests"
            copy.mkdir(parents=True)
            (copy / "test_thing.py").write_text(body)

        assert count_xfail_markers(tmp_path) == 1, (
            "worktree copies were counted; this is the false positive that "
            "failed the build over four xfails that did not exist"
        )

    def test_iter_test_files_skips_worktrees(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "test_real.py").write_text("")
        wt = tmp_path / ".claude" / "worktrees" / "agent-x" / "pkg"
        wt.mkdir(parents=True)
        (wt / "test_real.py").write_text("")

        found = iter_test_files(tmp_path)
        assert len(found) == 1
        assert not is_excluded(found[0])


@pytest.mark.unit
class TestXfailCounting:
    def test_counts_multiple_markers_in_one_file(self, tmp_path: Path) -> None:
        (tmp_path / "test_two.py").write_text(
            "import pytest\n"
            "@pytest.mark.xfail(reason='a')\n"
            "def test_a(): pass\n"
            "@pytest.mark.xfail(reason='b')\n"
            "def test_b(): pass\n"
        )
        assert count_xfail_markers(tmp_path) == 2

    def test_zero_when_no_markers(self, tmp_path: Path) -> None:
        (tmp_path / "test_clean.py").write_text("def test_a(): pass\n")
        assert count_xfail_markers(tmp_path) == 0

    def test_marker_inside_a_string_literal_is_not_counted(self, tmp_path: Path) -> None:
        """The gate must not count its own fixtures.

        An unanchored pattern matched `@pytest.mark.xfail` wherever it appeared,
        including inside the string literals THIS file uses to build fixtures.
        The gate then reported three disarmed guards that did not exist - the
        same false positive as the worktree bug, one level down.
        """
        (tmp_path / "test_meta.py").write_text(
            'BODY = "import pytest\\n@pytest.mark.xfail(reason=\'x\')\\ndef test_a(): pass"\n'
            "def test_uses_body(): assert BODY\n"
        )
        assert count_xfail_markers(tmp_path) == 0

    def test_real_decorator_is_still_counted_when_indented(self, tmp_path: Path) -> None:
        """Anchoring must not miss a decorator inside a class body."""
        (tmp_path / "test_indented.py").write_text(
            "import pytest\n\n\nclass TestThing:\n"
            "    @pytest.mark.xfail(reason='y')\n"
            "    def test_b(self): pass\n"
        )
        assert count_xfail_markers(tmp_path) == 1

    def test_undecodable_file_does_not_crash_the_gate(self, tmp_path: Path) -> None:
        """A gate that dies on a stray binary is a gate that gets removed."""
        (tmp_path / "test_binary.py").write_bytes(b"\xff\xfe\x00\x01")
        assert count_xfail_markers(tmp_path) == 0


@pytest.mark.unit
class TestParseCollected:
    def test_parses_deselected_form(self) -> None:
        assert parse_collected("1329/3408 tests collected (2079 deselected) in 1.2s") == 1329

    def test_parses_bare_form(self) -> None:
        assert parse_collected("3408 tests collected in 1.1s") == 3408

    def test_raises_rather_than_guessing(self) -> None:
        """Returning 0 on an unparseable run would silently pass the ratchet."""
        with pytest.raises(ValueError, match="could not parse"):
            parse_collected("pytest exploded")


@pytest.mark.unit
class TestBudgetSemantics:
    def test_equal_to_budget_passes(self) -> None:
        """A ratchet holds at its budget; only growth fails."""
        assert not Budget("unmarked", 1329, 1329, "#825").exceeded

    def test_over_budget_fails(self) -> None:
        assert Budget("unmarked", 1330, 1329, "#825").exceeded

    def test_under_budget_passes(self) -> None:
        assert not Budget("unmarked", 12, 1329, "#825").exceeded

    def test_missing_config_entry_means_zero_allowance(self) -> None:
        """An unconfigured budget must not default to permissive."""
        budgets = evaluate({}, unmarked=1, xfails=0)
        assert budgets[0].exceeded

    def test_clean_at_zero_renders_ok(self) -> None:
        assert "ok" in Budget("xfail", 0, 0, "#444").render()

    def test_nonzero_budget_renders_warn_not_pass(self) -> None:
        """Tech debt should stay visible while it is still owed."""
        assert "WARN" in Budget("xfail", 2, 2, "#444").render()
