"""The integration-skip census must see every path a skip travels, and nothing else.

Each case writes a small test tree and asks the census what it finds. The three
the task names are the spine: a skip without the marker fails, a marker without
an issue fails, and a marked skip passes. The rest pin the paths a skip takes
that a text grep misses (a fixture in a conftest, a fixture behind a fixture, a
helper the test calls) and the shapes that must NOT count, because a false
positive pushes people to put ``may_skip`` on tests that cannot skip.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_integration_skips import Finding, find_integration_skips

pytestmark = pytest.mark.unit

_DECLARED = '@pytest.mark.may_skip(reason="needs the event store", issue="#1984")'


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source))


def _census(root: Path) -> list[tuple[str, str]]:
    return [(f.test, f.kind) for f in find_integration_skips(root)]


# ---------------------------------------------------------------- the three named cases


def test_a_skip_without_the_marker_is_found(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/tests/test_store.py",
        """
        import pytest

        @pytest.mark.integration
        def test_round_trip():
            pytest.skip("no store")
        """,
    )
    [finding] = find_integration_skips(tmp_path)
    assert (finding.path, finding.test, finding.kind) == (
        "pkg/tests/test_store.py",
        "test_round_trip",
        "undeclared",
    )
    assert "test_store.py:6" in finding.detail


def test_a_marker_without_an_issue_is_malformed(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/tests/test_store.py",
        """
        import pytest

        @pytest.mark.integration
        @pytest.mark.may_skip(reason="needs the event store")
        def test_round_trip():
            pytest.skip("no store")
        """,
    )
    assert _census(tmp_path) == [("test_round_trip", "malformed")]


@pytest.mark.parametrize(
    "arguments",
    [
        'issue="#1984"',
        'reason="", issue="#1984"',
        'reason="needs docker", issue="1984"',
        'reason="needs docker", issue="#"',
        '"needs docker", "#1984"',
    ],
)
def test_an_opt_out_needs_a_named_reason_and_a_hash_issue(tmp_path: Path, arguments: str) -> None:
    _write(
        tmp_path,
        "test_x.py",
        f"""
        import pytest

        @pytest.mark.integration
        @pytest.mark.may_skip({arguments})
        def test_x():
            pytest.skip("no docker")
        """,
    )
    assert _census(tmp_path) == [("test_x", "malformed")]


def test_a_declared_skip_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/tests/test_store.py",
        f"""
        import pytest

        @pytest.mark.integration
        {_DECLARED}
        def test_round_trip():
            pytest.skip("no store")
        """,
    )
    assert find_integration_skips(tmp_path) == []


@pytest.mark.parametrize("where", ["module", "class"])
def test_a_declaration_on_the_module_or_class_covers_its_tests(tmp_path: Path, where: str) -> None:
    mark = _DECLARED.removeprefix("@")
    module_line = f"pytestmark = [pytest.mark.integration, {mark}]" if where == "module" else ""
    class_line = f"pytestmark = [pytest.mark.integration, {mark}]" if where == "class" else ""
    _write(
        tmp_path,
        "test_x.py",
        f"""
        import pytest

        {module_line}

        class TestStore:
            {class_line}

            def test_x(self):
                pytest.skip("no store")
        """,
    )
    assert find_integration_skips(tmp_path) == []


# ---------------------------------------------------------------- paths a skip travels


def test_a_module_skipif_marks_every_test(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_docker.py",
        """
        import shutil
        import pytest

        pytestmark = [
            pytest.mark.integration,
            pytest.mark.skipif(shutil.which("docker") is None, reason="docker"),
        ]

        def test_one():
            pass

        async def test_two():
            pass
        """,
    )
    assert _census(tmp_path) == [("test_one", "undeclared"), ("test_two", "undeclared")]


def test_a_fixture_in_a_parent_conftest_behind_another_fixture(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/tests/conftest.py",
        """
        import pytest

        @pytest.fixture
        def grpc_client():
            pytest.skip("event store not available")

        @pytest.fixture
        def repository_factory(grpc_client):
            return grpc_client
        """,
    )
    _write(
        tmp_path,
        "pkg/tests/integration/test_round_trip.py",
        """
        import pytest

        @pytest.mark.integration
        async def test_round_trip(repository_factory):
            assert repository_factory
        """,
    )
    [finding] = find_integration_skips(tmp_path)
    assert finding.kind == "undeclared"
    assert "'repository_factory' requests fixture 'grpc_client'" in finding.detail
    assert "pkg/tests/conftest.py" in finding.detail


def test_a_renamed_autouse_or_usefixtures_fixture_counts(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest
        from pytest import importorskip as need

        @pytest.fixture(name="minio")
        def _minio():
            need("boto3")

        @pytest.fixture(autouse=True)
        def _env():
            pytest.skip("unset")

        @pytest.mark.integration
        @pytest.mark.usefixtures("minio")
        def test_upload():
            pass
        """,
    )
    _write(
        tmp_path,
        "other/test_y.py",
        """
        import pytest

        @pytest.fixture
        def minio():
            pytest.skip("no minio")

        @pytest.mark.integration
        @pytest.mark.usefixtures("minio")
        def test_upload():
            pass
        """,
    )
    assert _census(tmp_path) == [("test_upload", "undeclared"), ("test_upload", "undeclared")]


def test_a_helper_the_test_calls_is_followed(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        def _probe(url):
            if not url:
                pytest.skip("no backend")

        def _require(url):
            _probe(url)

        class TestContract:
            pytestmark = pytest.mark.integration

            def _backend(self):
                _require("")

            def test_dedup(self):
                self._backend()
        """,
    )
    [finding] = find_integration_skips(tmp_path)
    assert "calls _backend(), which calls _require()" in finding.detail


def test_module_level_importorskip_skips_the_module(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        boto3 = pytest.importorskip("boto3")

        @pytest.mark.integration
        def test_upload():
            pass
        """,
    )
    assert _census(tmp_path) == [("test_upload", "undeclared")]


# ---------------------------------------------------------------- what must not count


def test_a_unit_test_that_skips_is_not_this_gates_business(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        @pytest.mark.unit
        def test_x():
            pytest.skip("not here")
        """,
    )
    assert find_integration_skips(tmp_path) == []


def test_an_integration_test_with_no_path_to_a_skip_is_clean(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        def helper():
            return 1

        @pytest.fixture
        def store():
            pytest.fail("a missing store is a failure, not a skip")

        @pytest.mark.integration
        def test_x(store, tmp_path):
            assert helper()
            assert "pytest.skip(" in "a string is not a call"
        """,
    )
    assert find_integration_skips(tmp_path) == []


def test_a_sibling_conftest_fixture_is_not_in_scope(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a/conftest.py",
        """
        import pytest

        @pytest.fixture
        def store():
            pytest.skip("no store")
        """,
    )
    _write(
        tmp_path,
        "b/test_x.py",
        """
        import pytest

        @pytest.fixture
        def store():
            return 1

        @pytest.mark.integration
        def test_x(store):
            pass
        """,
    )
    assert find_integration_skips(tmp_path) == []


def test_submodules_and_worktrees_are_not_scanned(tmp_path: Path) -> None:
    source = """
        import pytest

        @pytest.mark.integration
        def test_x():
            pytest.skip("x")
        """
    _write(tmp_path, "lib/event-sourcing-platform/tests/test_x.py", source)
    _write(tmp_path, ".claude/worktrees/agent/tests/test_x.py", source)
    _write(tmp_path, "pkg/tests/test_x.py", source)
    assert [f.path for f in find_integration_skips(tmp_path)] == ["pkg/tests/test_x.py"]


def test_render_names_the_node_and_the_route(tmp_path: Path) -> None:
    finding = Finding(path="a/test_x.py", test="test_x", kind="undeclared", detail="can skip: y")
    assert finding.render() == "a/test_x.py::test_x: can skip: y"
