"""The integration-skip checker must see every way a test can skip (PC-192/PC-193).

Three PRs in one week passed with their integration tests skipped: an image
defaulted to ``:latest``, a store was not provisioned, an env var was unset.
None of those skips was in the test body; two were in fixtures. So these tests
plant each shape as a real file tree and assert on what ``scan`` reports,
including that a declared skip passes and a half-written declaration does not.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_integration_skips import Finding, Problem, scan

pytestmark = pytest.mark.unit


def _plant(root: Path, files: dict[str, str]) -> list[Path]:
    paths = []
    for rel, source in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source))
        paths.append(path)
    return [p for p in paths if p.name.startswith("test_")]


def _scan(root: Path, files: dict[str, str]) -> list[tuple[str, Problem]]:
    findings: list[Finding] = scan(root, _plant(root, files), [root / "src"])
    return [(f.test, f.problem) for f in findings]


_UNDECLARED = Problem.UNDECLARED


def test_a_skip_in_the_body_without_the_marker_fails(tmp_path: Path) -> None:
    assert _scan(
        tmp_path,
        {
            "tests/test_a.py": """
                import os, pytest

                @pytest.mark.integration
                def test_store():
                    if not os.environ.get("STORE_URL"):
                        pytest.skip("no store")
            """
        },
    ) == [("test_store", _UNDECLARED)]


def test_a_marked_skip_passes(tmp_path: Path) -> None:
    assert (
        _scan(
            tmp_path,
            {
                "tests/test_a.py": """
                import pytest

                @pytest.mark.integration
                @pytest.mark.may_skip(reason="needs the Docker daemon", issue="#1234")
                def test_store():
                    pytest.skip("no docker")
            """
            },
        )
        == []
    )


def test_a_marker_without_an_issue_fails(tmp_path: Path) -> None:
    # Fails as a malformed declaration, and does not count as declared.
    assert _scan(
        tmp_path,
        {
            "tests/test_a.py": """
                import pytest

                @pytest.mark.integration
                @pytest.mark.may_skip(reason="needs the Docker daemon")
                def test_store():
                    pytest.skip("no docker")
            """
        },
    ) == [("test_store", Problem.NO_ISSUE)]


@pytest.mark.parametrize("issue", ['""', '"1234"', '"see #1234"', "ISSUE"])
def test_an_issue_that_is_not_a_literal_reference_fails(tmp_path: Path, issue: str) -> None:
    assert _scan(
        tmp_path,
        {
            "tests/test_a.py": f"""
                import pytest

                @pytest.mark.integration
                @pytest.mark.may_skip(reason="why", issue={issue})
                def test_store():
                    pass
            """
        },
    ) == [("test_store", Problem.NO_ISSUE)]


def test_a_marker_without_a_reason_fails(tmp_path: Path) -> None:
    assert _scan(
        tmp_path,
        {
            "tests/test_a.py": """
                import pytest

                @pytest.mark.integration
                @pytest.mark.may_skip(reason="  ", issue="syntropic137/syntropic137#1")
                def test_store():
                    pytest.skip("no docker")
            """
        },
    ) == [("test_store", Problem.NO_REASON)]


def test_a_skip_in_a_conftest_fixture_fails(tmp_path: Path) -> None:
    # The shape behind "a store was not provisioned": the test body is clean.
    assert _scan(
        tmp_path,
        {
            "tests/conftest.py": """
                import pytest

                @pytest.fixture
                def store_url():
                    pytest.skip("event store not available")

                @pytest.fixture
                def store(store_url):
                    return store_url
            """,
            "tests/integration/test_a.py": """
                import pytest

                pytestmark = pytest.mark.integration

                def test_roundtrip(store):
                    assert store
            """,
        },
    ) == [("test_roundtrip", _UNDECLARED)]


def test_an_autouse_or_usefixtures_fixture_that_skips_fails(tmp_path: Path) -> None:
    assert _scan(
        tmp_path,
        {
            "tests/a/conftest.py": """
                import pytest

                @pytest.fixture(autouse=True)
                def _docker():
                    pytest.importorskip("docker")
            """,
            "tests/a/test_a.py": """
                import pytest

                @pytest.mark.integration
                def test_auto():
                    pass
            """,
            "tests/b/test_b.py": """
                import pytest

                @pytest.fixture
                def env():
                    pytest.skip("unset")

                @pytest.mark.integration
                @pytest.mark.usefixtures("env")
                def test_used():
                    pass
            """,
        },
    ) == [("test_auto", _UNDECLARED), ("test_used", _UNDECLARED)]


def test_a_skip_in_a_helper_imported_from_another_module_fails(tmp_path: Path) -> None:
    assert _scan(
        tmp_path,
        {
            "src/helpers/docker.py": """
                from pytest import skip as _skip

                def require_docker():
                    _skip("no docker")
            """,
            "tests/test_a.py": """
                import pytest
                from helpers.docker import require_docker

                class TestReap:
                    pytestmark = [pytest.mark.integration]

                    def test_reaps(self):
                        require_docker()
            """,
        },
    ) == [("TestReap::test_reaps", _UNDECLARED)]


def test_skip_marks_and_module_level_skips_fail(tmp_path: Path) -> None:
    assert _scan(
        tmp_path,
        {
            "tests/test_mark.py": """
                import os, pytest

                @pytest.mark.integration
                @pytest.mark.skipif(not os.environ.get("IMAGE"), reason="unset")
                def test_image():
                    pass
            """,
            "tests/test_module.py": """
                import pytest

                docker = pytest.importorskip("docker")
                pytestmark = pytest.mark.integration

                def test_client():
                    pass
            """,
        },
    ) == [("test_image", _UNDECLARED), ("test_client", _UNDECLARED)]


def test_integration_applied_through_a_parametrized_fixture_counts(tmp_path: Path) -> None:
    assert _scan(
        tmp_path,
        {
            "tests/test_a.py": """
                import pytest

                @pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
                def backend(request):
                    if request.param == "postgres":
                        pytest.skip("no postgres")
                    return request.param

                def test_backend(backend):
                    pass
            """
        },
    ) == [("test_backend", _UNDECLARED)]


def test_a_module_level_declaration_covers_every_test(tmp_path: Path) -> None:
    assert (
        _scan(
            tmp_path,
            {
                "tests/test_a.py": """
                import pytest

                pytestmark = [
                    pytest.mark.integration,
                    pytest.mark.may_skip(reason="needs docker", issue="#7"),
                ]

                def test_one():
                    pytest.skip("no docker")

                def test_two():
                    pytest.skip("no docker")
            """
            },
        )
        == []
    )


def test_tests_that_cannot_skip_or_are_not_integration_pass(tmp_path: Path) -> None:
    assert (
        _scan(
            tmp_path,
            {
                "tests/test_a.py": """
                import pytest

                @pytest.mark.integration
                def test_real():
                    assert 1

                @pytest.mark.unit
                def test_unit_skip():
                    pytest.skip("not integration, not this gate's business")

                def _recursive(n):
                    return _recursive(n - 1) if n else 0

                @pytest.mark.integration
                def test_recursion_is_not_a_skip():
                    _recursive(3)
            """
            },
        )
        == []
    )


# Each shape below skips under real pytest without a skip call in the test body
# or a skip mark on the test itself. The checker must see all of them, and each
# test also runs the planted tree through pytest so the checker's model of
# pytest cannot drift from pytest unnoticed.
_SHAPES: dict[str, tuple[str, dict[str, str]]] = {
    "parameter_skip_mark": (
        "test_real",
        {
            "tests/test_a.py": """
                import pytest

                @pytest.mark.integration
                @pytest.mark.parametrize("n", [pytest.param(1, marks=pytest.mark.skip(reason="no store"))])
                def test_real(n):
                    pass
            """
        },
    ),
    "fixture_parameter_skip_mark": (
        "test_real",
        {
            "tests/test_a.py": """
                import pytest

                @pytest.fixture(params=[pytest.param(1, marks=pytest.mark.skipif(True, reason="no store"))])
                def store(request):
                    return request.param

                @pytest.mark.integration
                def test_real(store):
                    pass
            """
        },
    ),
    "class_fixture": (
        "TestReal::test_real",
        {
            "tests/test_a.py": """
                import pytest

                @pytest.mark.integration
                class TestReal:
                    @pytest.fixture
                    def store(self):
                        pytest.skip("no store")

                    def test_real(self, store):
                        pass
            """
        },
    ),
    "renamed_fixture": (
        "test_real",
        {
            "tests/test_a.py": """
                import pytest

                @pytest.fixture(name="store")
                def _store():
                    pytest.skip("no store")

                @pytest.mark.integration
                def test_real(store):
                    pass
            """
        },
    ),
    "pytest_module_alias": (
        "test_real",
        {
            "tests/test_a.py": """
                import pytest as pt

                @pt.mark.integration
                def test_real():
                    pt.skip("no store")
            """
        },
    ),
    "package_reexport": (
        "test_real",
        {
            "src/helpers/__init__.py": """
                from .requirement import require_store
            """,
            "src/helpers/requirement.py": """
                import pytest

                def require_store():
                    pytest.skip("no store")
            """,
            "tests/test_a.py": """
                import pytest
                from helpers import require_store

                @pytest.mark.integration
                def test_real():
                    require_store()
            """,
        },
    ),
    "setup_method": (
        "TestReal::test_real",
        {
            "tests/test_a.py": """
                import pytest

                @pytest.mark.integration
                class TestReal:
                    def setup_method(self):
                        pytest.skip("no store")

                    def test_real(self):
                        pass
            """
        },
    ),
    "setup_module": (
        "test_real",
        {
            "tests/test_a.py": """
                import pytest

                def setup_module():
                    pytest.skip("no store")

                @pytest.mark.integration
                def test_real():
                    pass
            """
        },
    ),
}

_PYTEST_INI = """\
[pytest]
pythonpath = src
markers =
    integration: x
    may_skip(reason, issue): x
"""


def _with_declaration(files: dict[str, str], declaration: str) -> dict[str, str]:
    declared = dict(files)
    declared["tests/test_a.py"] = (
        textwrap.dedent(files["tests/test_a.py"])
        + f"\nimport pytest\npytestmark = pytest.mark.may_skip({declaration})\n"
    )
    return declared


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_skip_pytest_reaches_without_a_marker_fails(tmp_path: Path, shape: str) -> None:
    test, files = _SHAPES[shape]
    assert _scan(tmp_path, files) == [(test, _UNDECLARED)]
    (tmp_path / "pytest.ini").write_text(_PYTEST_INI)
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-q",
            "-m",
            "integration",
            "tests",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "1 skipped" in run.stdout, run.stdout + run.stderr


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_declared_skip_of_each_shape_passes(tmp_path: Path, shape: str) -> None:
    _, files = _SHAPES[shape]
    assert _scan(tmp_path, _with_declaration(files, 'reason="no store", issue="#1982"')) == []


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_malformed_declaration_of_each_shape_fails(tmp_path: Path, shape: str) -> None:
    test, files = _SHAPES[shape]
    assert _scan(tmp_path, _with_declaration(files, 'reason="no store"')) == [
        (test, Problem.NO_ISSUE)
    ]
