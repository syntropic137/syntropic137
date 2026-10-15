"""The integration-skip checker must see every way a test can skip (PC-192/PC-193).

Three PRs in one week passed with their integration tests skipped: an image
defaulted to ``:latest``, a store was not provisioned, an env var was unset.
None of those skips was in the test body; two were in fixtures. So these tests
plant each shape as a real file tree and assert on what ``scan`` reports,
including that a declared skip passes and a half-written declaration does not.
"""

from __future__ import annotations

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
