"""The integration-skip census must see every path a skip travels, and nothing else.

Each case writes a small test tree and asks the census what it finds. The three
the task names are the spine: a skip without the marker fails, a marker without
an issue fails, and a marked skip passes. The rest pin the paths a skip takes
that a text grep misses (a fixture in a conftest, a fixture behind a fixture, a
helper the test calls) and the shapes that must NOT count, because a false
positive pushes people to put ``may_skip`` on tests that cannot skip.
"""

from __future__ import annotations

import subprocess
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


def test_a_fixture_requested_by_its_name_override_counts(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        @pytest.fixture(name="minio")
        def _minio():
            pytest.skip("no minio")

        @pytest.mark.integration
        @pytest.mark.usefixtures("minio")
        def test_upload():
            pass
        """,
    )
    assert _census(tmp_path) == [("test_upload", "undeclared")]


def test_an_autouse_fixture_counts(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        @pytest.fixture(autouse=True)
        def _env():
            pytest.skip("unset")

        @pytest.mark.integration
        def test_upload():
            pass
        """,
    )
    assert _census(tmp_path) == [("test_upload", "undeclared")]


def test_a_renamed_importorskip_counts(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest
        from pytest import importorskip as need

        @pytest.mark.integration
        def test_upload():
            need("boto3")
        """,
    )
    assert _census(tmp_path) == [("test_upload", "undeclared")]


def test_an_aliased_pytest_module_skips_and_marks(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest as pt

        @pt.mark.integration
        def test_store():
            pt.skip("no store")

        @pt.mark.integration
        @pt.mark.may_skip(reason="no store", issue="#1")
        def test_declared():
            pt.skip("no store")
        """,
    )
    assert _census(tmp_path) == [("test_store", "undeclared")]


def test_a_directly_imported_mark_is_a_marker(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest
        from pytest import mark

        @mark.integration
        def test_store():
            pytest.skip("no store")

        @mark.integration
        @mark.may_skip(reason="no store", issue="#1")
        def test_declared():
            pytest.skip("no store")
        """,
    )
    assert _census(tmp_path) == [("test_store", "undeclared")]


# ---------------------------------------------------------------- scope


def test_a_class_fixture_does_not_hide_the_module_fixture(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        @pytest.fixture
        def store():
            pytest.skip("no store")

        class TestOther:
            @pytest.fixture
            def store(self):
                return 1

        @pytest.mark.integration
        def test_x(store):
            pass
        """,
    )
    assert _census(tmp_path) == [("test_x", "undeclared")]


def test_another_classes_autouse_fixture_is_not_in_scope(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        class TestUnit:
            @pytest.fixture(autouse=True)
            def _env(self):
                pytest.skip("unit only")

            def test_u(self):
                pass

        @pytest.mark.integration
        def test_x():
            pass
        """,
    )
    assert find_integration_skips(tmp_path) == []


def test_an_inherited_fixture_that_skips_counts(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        class Base:
            @pytest.fixture
            def backend(self):
                pytest.skip("base backend missing")

        @pytest.mark.integration
        class TestDerived(Base):
            def test_store(self, backend):
                pass
        """,
    )
    assert _census(tmp_path) == [("TestDerived::test_store", "undeclared")]


def test_an_inherited_autouse_fixture_counts(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        class Base:
            @pytest.fixture(autouse=True)
            def _env(self):
                pytest.skip("no env")

        @pytest.mark.integration
        class TestDerived(Base):
            def test_store(self):
                pass
        """,
    )
    assert _census(tmp_path) == [("TestDerived::test_store", "undeclared")]


def test_a_subclass_override_replaces_the_inherited_fixture(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        class Base:
            @pytest.fixture
            def backend(self):
                pytest.skip("base backend missing")

        @pytest.mark.integration
        class TestDerived(Base):
            @pytest.fixture
            def backend(self):
                return 1

            def test_store(self, backend):
                pass
        """,
    )
    assert find_integration_skips(tmp_path) == []


def test_a_diamond_takes_the_fixture_its_mro_reaches_first(tmp_path: Path) -> None:
    # MRO is TestDerived, Left, Right, Root: Right's override hides Root's,
    # even though Left (searched first) inherits Root's.
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        class Root:
            @pytest.fixture
            def backend(self):
                return 1

        class Left(Root):
            pass

        class Right(Root):
            @pytest.fixture
            def backend(self):
                pytest.skip("right backend missing")

        @pytest.mark.integration
        class TestDerived(Left, Right):
            def test_store(self, backend):
                pass
        """,
    )
    assert _census(tmp_path) == [("TestDerived::test_store", "undeclared")]


def test_a_diamond_resolves_self_calls_in_mro_order(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        class Root:
            def setup_backend(self):
                return 1

        class Left(Root):
            pass

        class Right(Root):
            def setup_backend(self):
                pytest.skip("right backend missing")

        @pytest.mark.integration
        class TestDerived(Left, Right):
            def test_store(self):
                self.setup_backend()
        """,
    )
    assert _census(tmp_path) == [("TestDerived::test_store", "undeclared")]


def test_class_hierarchies_python_rejects_do_not_stop_the_census(tmp_path: Path) -> None:
    # TestOrder's bases have no C3 order (TypeError at import); TestLoop's
    # rebound names make each class its own ancestor here. Neither may hang or
    # crash the census, and the clean file beside them is still read.
    _write(
        tmp_path,
        "test_bad.py",
        """
        import pytest

        class X:
            pass

        class Y(X):
            pass

        class TestOrder(X, Y):
            def test_o(self):
                pass

        class A:
            pass

        class B(A):
            pass

        class A(B):
            pass

        class TestLoop(A):
            def test_l(self):
                self.missing()
        """,
    )
    _write(
        tmp_path,
        "test_good.py",
        """
        import pytest

        @pytest.mark.integration
        def test_i():
            pytest.skip("no backend")
        """,
    )
    assert _census(tmp_path) == [("test_i", "undeclared")]


def test_self_calls_resolve_in_the_tests_own_class(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        class TestUnit:
            def backend(self):
                pytest.skip("unit only")

            def test_u(self):
                self.backend()

        @pytest.mark.integration
        class TestIntegration:
            def backend(self):
                return 1

            def test_i(self):
                self.backend()

        @pytest.mark.integration
        class TestSkipping(TestUnit):
            def test_inherited(self):
                self.backend()
        """,
    )
    assert _census(tmp_path) == [("TestSkipping::test_inherited", "undeclared")]


# ---------------------------------------------------------------- parameter legs


def test_an_integration_leg_of_a_fixture_parameter_counts(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        @pytest.fixture(
            params=[
                pytest.param("memory", marks=pytest.mark.unit),
                pytest.param("minio", marks=pytest.mark.integration),
            ]
        )
        def storage(request):
            if request.param == "minio":
                pytest.skip("no minio")
            return request.param

        @pytest.fixture
        def wrapped(storage):
            return storage

        def test_x(wrapped):
            pass
        """,
    )
    assert _census(tmp_path) == [("test_x", "undeclared")]


def test_an_integration_leg_of_a_parametrize_counts(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        @pytest.mark.parametrize(
            "backend", [pytest.param("memory"), pytest.param("pg", marks=[pytest.mark.integration])]
        )
        def test_x(backend):
            pytest.skip("no pg")
        """,
    )
    assert _census(tmp_path) == [("test_x", "undeclared")]


def test_a_unit_only_parameter_leg_is_not_this_gates_business(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        @pytest.mark.parametrize("backend", [pytest.param("memory", marks=pytest.mark.unit)])
        def test_x(backend):
            pytest.skip("unit")
        """,
    )
    assert find_integration_skips(tmp_path) == []


def test_a_parameter_skipif_on_an_integration_test_counts(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        @pytest.mark.integration
        @pytest.mark.parametrize(
            "backend",
            ["memory", pytest.param("pg", marks=pytest.mark.skipif(True, reason="no pg"))],
        )
        def test_x(backend):
            pass
        """,
    )
    [finding] = find_integration_skips(tmp_path)
    assert (finding.test, finding.kind) == ("test_x", "undeclared")
    assert "marked skipif" in finding.detail


def test_an_opt_out_on_one_leg_does_not_cover_another(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        @pytest.fixture(
            params=[
                pytest.param("redis", marks=[pytest.mark.integration, pytest.mark.may_skip(reason="no redis", issue="#1")]),
                pytest.param("pg", marks=pytest.mark.integration),
            ]
        )
        def store(request):
            pytest.skip("no backend")

        def test_x(store):
            pass
        """,
    )
    [finding] = find_integration_skips(tmp_path)
    assert (finding.test, finding.kind) == ("test_x", "undeclared")
    assert "parameter set 1" in finding.detail


def test_a_declared_leg_passes_and_a_malformed_one_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        @pytest.fixture(
            params=[
                pytest.param("memory", marks=pytest.mark.unit),
                pytest.param("pg", marks=[pytest.mark.integration, pytest.mark.may_skip(reason="no pg", issue="#1")]),
            ]
        )
        def good(request):
            pytest.skip("no backend")

        @pytest.fixture(
            params=[pytest.param("pg", marks=[pytest.mark.integration, pytest.mark.may_skip(reason="no pg")])]
        )
        def bad(request):
            pytest.skip("no backend")

        def test_good(good):
            pass

        def test_bad(bad):
            pass
        """,
    )
    assert _census(tmp_path) == [("test_bad", "malformed")]


_ALIASED_CONFTEST = """
import pytest as pt

@pt.fixture(params=[pt.param("pg", marks=[pt.mark.integration{declaration}])])
def backend(request):
    pt.skip("pg missing")
"""


@pytest.mark.parametrize(
    ("declaration", "expected"),
    [
        ("", [("test_store", "undeclared")]),
        (', pt.mark.may_skip(reason="no pg", issue="#1")', []),
        (', pt.mark.may_skip(reason="no pg")', [("test_store", "malformed")]),
    ],
    ids=["undeclared", "declared", "malformed"],
)
def test_a_conftest_parameters_marks_are_read_with_the_conftests_imports(
    tmp_path: Path, declaration: str, expected: list[tuple[str, str]]
) -> None:
    # The test module imports nothing: ``pt`` exists only in the conftest.
    _write(tmp_path, "conftest.py", _ALIASED_CONFTEST.format(declaration=declaration))
    _write(
        tmp_path,
        "test_store.py",
        """
        def test_store(backend):
            pass
        """,
    )
    assert _census(tmp_path) == expected


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
        "conftest.py",
        """
        import pytest

        @pytest.fixture
        def store():
            return 1
        """,
    )
    _write(
        tmp_path,
        "a/conftest.py",
        """
        import pytest

        @pytest.fixture
        def store():
            pytest.skip("no store")

        @pytest.fixture(autouse=True)
        def _trap():
            pytest.skip("sibling autouse")
        """,
    )
    _write(
        tmp_path,
        "b/test_x.py",
        """
        import pytest

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


def test_an_inherited_helper_dispatches_self_calls_from_the_tests_class(tmp_path: Path) -> None:
    # Root.prepare() is inherited; its self.setup_backend() is TestDerived's
    # lookup, which reaches Right's skipping override before Root's.
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        class Root:
            def setup_backend(self):
                return 1

            def prepare(self):
                self.setup_backend()

        class Left(Root):
            pass

        class Right(Root):
            def setup_backend(self):
                pytest.skip("right backend missing")

        @pytest.mark.integration
        class TestDerived(Left, Right):
            def test_store(self):
                self.prepare()
        """,
    )
    assert _census(tmp_path) == [("TestDerived::test_store", "undeclared")]


def test_an_inherited_fixture_dispatches_self_calls_from_the_tests_class(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_x.py",
        """
        import pytest

        class Root:
            def setup_backend(self):
                return 1

            @pytest.fixture
            def backend(self):
                return self.setup_backend()

        class Left(Root):
            pass

        class Right(Root):
            def setup_backend(self):
                pytest.skip("right backend missing")

        @pytest.mark.integration
        class TestDerived(Left, Right):
            def test_store(self, backend):
                pass
        """,
    )
    assert _census(tmp_path) == [("TestDerived::test_store", "undeclared")]


_CLEAN = """
@pytest.mark.integration
class TestClean(Root):
    def test_store(self):
        self.prepare()
"""

_SKIPPING = """
@pytest.mark.integration
class TestSkipping(Root):
    def setup_backend(self):
        pytest.skip("subclass backend missing")

    def test_store(self):
        self.prepare()
"""


@pytest.mark.parametrize(
    "order", [(_CLEAN, _SKIPPING), (_SKIPPING, _CLEAN)], ids=["clean-first", "skipping-first"]
)
def test_a_shared_inherited_helper_is_answered_per_receiver(
    tmp_path: Path, order: tuple[str, str]
) -> None:
    # Both classes inherit Root.prepare(); only TestSkipping's override skips.
    # Whichever class is read first must not answer for the other.
    root = """
import pytest

class Root:
    def setup_backend(self):
        return 1

    def prepare(self):
        self.setup_backend()
"""
    _write(tmp_path, "test_x.py", root + "".join(order))
    assert _census(tmp_path) == [("TestSkipping::test_store", "undeclared")]


def test_a_skip_in_a_helper_imported_from_another_module_counts(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["src"]\n')
    _write(
        tmp_path,
        "src/helpers/__init__.py",
        "from .docker import require_docker as require_docker\n",
    )
    _write(
        tmp_path,
        "src/helpers/docker.py",
        """
        from pytest import skip as _skip

        def require_docker():
            _check()

        def _check():
            _skip("no docker")
        """,
    )
    _write(
        tmp_path,
        "tests/test_a.py",
        """
        import pytest
        from helpers import require_docker as docker

        class TestReap:
            pytestmark = [pytest.mark.integration]

            def test_reaps(self):
                docker()
        """,
    )
    assert _census(tmp_path) == [("TestReap::test_reaps", "undeclared")]


# ---------------------------------------------------------------- parity with real pytest

_PYTEST_INI = "[pytest]\nmarkers =\n    integration: i\n    may_skip(reason, issue): m\n"

#: Fixture override chains, imported fixtures and mixed parameter legs, each
#: with the outcome a real ``pytest -m integration`` run gives it.
_PARITY: dict[str, tuple[dict[str, str], str, bool]] = {
    "conftest_dependency_override": (
        {
            "tests/conftest.py": """
            import pytest
            @pytest.fixture
            def transport():
                return 1
            @pytest.fixture
            def store(transport):
                return transport
            """,
            "tests/test_x.py": """
            import pytest
            @pytest.fixture
            def transport():
                pytest.skip("no transport")
            @pytest.mark.integration
            def test_x(store):
                pass
            """,
        },
        "1 skipped",
        True,
    ),
    "fixture_override_requests_parent": (
        {
            "tests/conftest.py": """
            import pytest
            @pytest.fixture
            def store():
                pytest.skip("no store")
            """,
            "tests/test_x.py": """
            import pytest
            @pytest.fixture
            def store(store):
                return store
            @pytest.mark.integration
            def test_x(store):
                pass
            """,
        },
        "1 skipped",
        True,
    ),
    "imported_autouse": (
        {
            "tests/__init__.py": "",
            "tests/helpers.py": """
            import pytest
            @pytest.fixture(autouse=True)
            def need_store():
                pytest.skip("no store")
            """,
            "tests/test_x.py": """
            import pytest
            from tests.helpers import need_store
            @pytest.mark.integration
            def test_x():
                pass
            """,
        },
        "1 skipped",
        True,
    ),
    "imported_fixture_under_an_alias": (
        {
            "tests/__init__.py": "",
            "tests/support/__init__.py": "from .stores import backend\n",
            "tests/support/stores.py": """
            import pytest
            @pytest.fixture
            def backend():
                pytest.skip("no store")
            """,
            "tests/test_x.py": """
            import pytest
            from tests.support import backend as store
            @pytest.mark.integration
            def test_x(store):
                pass
            """,
        },
        "1 skipped",
        True,
    ),
    "imported_fixture_keeps_an_explicit_name": (
        {
            "tests/__init__.py": "",
            "tests/helpers.py": """
            import pytest
            @pytest.fixture(name="backend")
            def backend():
                pytest.skip("no backend")
            """,
            "tests/test_x.py": """
            import pytest
            from tests.helpers import backend as alias
            @pytest.mark.integration
            def test_x(backend):
                pass
            """,
        },
        "1 skipped",
        True,
    ),
    "overridden_autouse_no_longer_skips": (
        {
            "tests/conftest.py": """
            import pytest
            @pytest.fixture(autouse=True)
            def need_store():
                pytest.skip("no store")
            """,
            "tests/test_x.py": """
            import pytest
            @pytest.fixture
            def need_store():
                return 1
            @pytest.mark.integration
            def test_x():
                pass
            """,
        },
        "1 passed",
        False,
    ),
    "declared_parameter": (
        {
            "tests/test_x.py": """
            import pytest
            @pytest.mark.parametrize("n", [pytest.param(1, marks=[
                pytest.mark.integration,
                pytest.mark.skip(reason="no store"),
                pytest.mark.may_skip(reason="no store", issue="#1984"),
            ])])
            def test_x(n):
                pass
            """,
        },
        "1 skipped",
        False,
    ),
    "unit_skip_and_integration_pass": (
        {
            "tests/test_x.py": """
            import pytest
            @pytest.mark.parametrize("n", [
                pytest.param(1, marks=pytest.mark.skip(reason="unit only")),
                pytest.param(2, marks=pytest.mark.integration),
            ])
            def test_x(n):
                pass
            """,
        },
        "1 passed, 1 deselected",
        False,
    ),
}


@pytest.mark.parametrize("shape", sorted(_PARITY))
def test_the_census_agrees_with_pytest(tmp_path: Path, shape: str) -> None:
    files, outcome, undeclared = _PARITY[shape]
    (tmp_path / "pytest.ini").write_text(_PYTEST_INI)
    for rel, source in files.items():
        _write(tmp_path, rel, source)
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-m", "integration", "-p", "no:cacheprovider"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.stdout.strip().splitlines()[-1].startswith(outcome), run.stdout
    expected = [("test_x", "undeclared")] if undeclared else []
    assert _census(tmp_path) == expected
