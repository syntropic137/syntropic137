"""The version-literal detector catches every spelling, and nothing else (#1389).

Planted sources, each caught with no allowlist involved, and clean ones that
must not be flagged, because a false positive teaches people to dodge the gate.
FastAPI is matched by what a name resolves to, not how it is spelled: the
#1188 lesson from ``check_untyped_dicts``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_version_literals import (
    DUNDER,
    FASTAPI,
    ExceptionEntry,
    Finding,
    exception_problems,
    is_test_file,
    violations,
)

pytestmark = pytest.mark.unit

DUNDER_PLANTED: dict[str, str] = {
    "plain": '__version__ = "0.1.0"\n',
    "annotated": '__version__: str = "1.2.3"\n',
    "chained": '__version__ = VERSION = "1.2.3"\n',
    "tuple unpacked": '__version__, _x = "1.2.3", 2\n',
    "under if": 'import sys\nif sys.version_info >= (3, 12):\n    __version__ = "1"\n',
    "under else": 'if False:\n    pass\nelse:\n    __version__ = "1"\n',
    "in try": 'try:\n    __version__ = "1"\nexcept Exception:\n    pass\n',
    "in except": 'try:\n    pass\nexcept Exception:\n    __version__ = "1"\n',
    "in finally": 'try:\n    pass\nfinally:\n    __version__ = "1"\n',
    "in try star": 'try:\n    pass\nexcept* ValueError:\n    __version__ = "1"\n',
    "in with": 'from contextlib import nullcontext\nwith nullcontext():\n    __version__ = "1.2.3"\n',
    "in for": 'for _ in [1]:\n    __version__ = "1"\n',
    "in for else": 'for _ in []:\n    pass\nelse:\n    __version__ = "1"\n',
    "in while": 'while True:\n    __version__ = "1"\n    break\n',
    "in match": 'match 1:\n    case 1:\n        __version__ = "1"\n',
    "nested compound": 'if True:\n    with x:\n        for _ in y:\n            __version__ = "1"\n',
}

FASTAPI_PLANTED: dict[str, str] = {
    "from import": 'from fastapi import FastAPI\napp = FastAPI(version="0.1.0")\n',
    "from import as": 'from fastapi import FastAPI as API\napp = API(version="1.2.3")\n',
    "from submodule": 'from fastapi.applications import FastAPI\napp = FastAPI(version="1")\n',
    "module attr": 'import fastapi\napp = fastapi.FastAPI(title="x", version="2")\n',
    "module alias": 'import fastapi as f\napp = f.FastAPI(version="2")\n',
    "dotted import": 'import fastapi.applications\napp = fastapi.FastAPI(version="2")\n',
    "renamed": 'from fastapi import FastAPI\nAPI = FastAPI\napp = API(version="1")\n',
    "rename chain": 'from fastapi import FastAPI\nA = FastAPI\nB = A\napp = B(version="1")\n',
    "annotated rename": (
        'import fastapi\nAPI: type[fastapi.FastAPI] = fastapi.FastAPI\napp = API(version="1")\n'
    ),
    "subclass": (
        "from fastapi import FastAPI\n"
        "class _TimedFastAPI(FastAPI):\n    pass\n"
        'app = _TimedFastAPI(version="0.5.1")\n'
    ),
    "subclass via module": (
        'import fastapi\nclass Timed(fastapi.FastAPI):\n    pass\napp = Timed(version="1")\n'
    ),
    "subclass of subclass": (
        "from fastapi import FastAPI\nclass A(FastAPI):\n    pass\nclass B(A):\n    pass\n"
        'app = B(version="1")\n'
    ),
    "inside a function": (
        'from fastapi import FastAPI\ndef create():\n    return FastAPI(version="1")\n'
    ),
}

CLEAN: dict[str, str] = {
    "derived dunder": "from importlib.metadata import version\n__version__ = version('x')\n",
    "derived FastAPI": "from fastapi import FastAPI\napp = FastAPI(version=version_string())\n",
    "function-local dunder": 'def f():\n    __version__ = "1"\n    return __version__\n',
    "class attribute dunder": 'class C:\n    __version__ = "1"\n',
    "dunder in method under if": 'if True:\n    def f():\n        __version__ = "1"\n',
    "other kwarg": 'from fastapi import FastAPI\napp = FastAPI(title="0.1.0")\n',
    "other callee": 'x = Model(version="1.0.0")\n',
    "unrelated name ending in FastAPI": 'class MyFastAPI:\n    pass\napp = MyFastAPI(version="1")\n',
    "unbound name ending in FastAPI": 'app = _TimedFastAPI(version="1")\n',
    "FastAPI from elsewhere": 'from mylib import FastAPI\napp = FastAPI(version="1")\n',
    "attr on another module": 'import mylib\napp = mylib.FastAPI(version="1")\n',
    "annotation only": "__version__: str\n",
}


@pytest.mark.parametrize("source", DUNDER_PLANTED.values(), ids=DUNDER_PLANTED.keys())
def test_planted_dunder_is_caught(source: str) -> None:
    assert [f.shape for f in violations(source)] == [DUNDER]


@pytest.mark.parametrize("source", FASTAPI_PLANTED.values(), ids=FASTAPI_PLANTED.keys())
def test_planted_fastapi_version_is_caught(source: str) -> None:
    assert [f.shape for f in violations(source)] == [FASTAPI]


@pytest.mark.parametrize("source", CLEAN.values(), ids=CLEAN.keys())
def test_clean_source_is_not_flagged(source: str) -> None:
    assert violations(source) == []


def test_ui_feedback_main_as_it_was_is_caught() -> None:
    """The real pre-#1389 shape, not a near miss."""
    before = (
        "from fastapi import FastAPI\n"
        "app = FastAPI(\n"
        '    title="UI Feedback API",\n'
        '    description="REST API for capturing and managing UI feedback",\n'
        '    version="0.1.0",\n'
        "    lifespan=lifespan,\n"
        ")\n"
    )
    assert violations(before) == [Finding(2, FASTAPI)]


@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        ("pkg/src/mod.py", False),
        ("pkg/tests/helpers.py", True),
        ("pkg/src/test_mod.py", True),
        ("pkg/src/mod_test.py", True),
        ("pkg/conftest.py", True),
    ],
)
def test_test_files_are_excluded(rel: str, expected: bool) -> None:
    assert is_test_file(rel) is expected


_SUB = "lib/sub"
_FILE = f"{_SUB}/pkg/__init__.py"


def _problems(
    entries: dict[str, ExceptionEntry],
    found: dict[str, int],
    checked_out: bool = True,
    exists: bool = True,
) -> list[str]:
    return exception_problems(entries, found, {_SUB: checked_out}, lambda _rel: exists)


def test_a_matching_entry_is_fine() -> None:
    assert _problems({_FILE: ExceptionEntry(1, "#1")}, {_FILE: 1}) == []


def test_an_in_tree_path_cannot_be_excepted() -> None:
    problems = _problems({"apps/x/mod.py": ExceptionEntry(1, "#1")}, {"apps/x/mod.py": 1})
    assert problems == ["apps/x/mod.py: not inside a submodule; fix it here instead"]


def test_a_path_that_only_shares_a_prefix_is_not_inside_the_submodule() -> None:
    rel = "lib/subway/mod.py"
    assert "not inside a submodule" in _problems({rel: ExceptionEntry(1, "#1")}, {rel: 1})[0]


def test_an_entry_needs_an_issue() -> None:
    assert _problems({_FILE: ExceptionEntry(1, "")}, {_FILE: 1}) == [f"{_FILE}: no issue"]


def test_a_lower_count_is_stale() -> None:
    problems = _problems({_FILE: ExceptionEntry(1, "#1")}, {})
    assert problems == [f"{_FILE}: fewer violations than listed; lower or delete the entry"]


def test_a_file_deleted_from_a_checked_out_submodule_is_stale() -> None:
    problems = _problems({_FILE: ExceptionEntry(1, "#1")}, {}, exists=False)
    assert problems == [f"{_FILE}: file no longer exists in {_SUB}; delete the entry"]


def test_an_uninitialized_submodule_is_not_measured() -> None:
    assert _problems({_FILE: ExceptionEntry(1, "#1")}, {}, checked_out=False, exists=False) == []
