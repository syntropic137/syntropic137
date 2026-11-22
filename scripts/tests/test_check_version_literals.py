"""The version-literal detector catches every spelling, and nothing else (#1389).

Planted sources, each caught with no allowlist involved, and clean ones that
must not be flagged, because a false positive teaches people to dodge the gate.
FastAPI is matched by what a name resolves to, not how it is spelled: the
#1188 lesson from ``check_untyped_dicts``.
"""

from __future__ import annotations

import signal
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import FrameType

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
    # #2104: module aliases and qualified module paths.
    "module rebound by assignment": ('import fastapi\nf = fastapi\napp = f.FastAPI(version="1")\n'),
    "module alias chain": 'import fastapi as a\nb = a\nc = b\napp = c.FastAPI(version="1")\n',
    "qualified submodule path": (
        'import fastapi.applications\napp = fastapi.applications.FastAPI(version="1")\n'
    ),
    "submodule imported as": ('import fastapi.applications as fa\napp = fa.FastAPI(version="1")\n'),
    "submodule from package": (
        'from fastapi import applications\napp = applications.FastAPI(version="1")\n'
    ),
    "subclass via qualified path": (
        "import fastapi.applications\n"
        "class T(fastapi.applications.FastAPI):\n    pass\n"
        'app = T(version="1")\n'
    ),
    # #2104: scopes still see what they should.
    "import in the same function": (
        'def f():\n    from fastapi import FastAPI\n    return FastAPI(version="1")\n'
    ),
    "import seen by a nested function": (
        "def f():\n    from fastapi import FastAPI\n"
        '    def g():\n        return FastAPI(version="1")\n    return g\n'
    ),
    "global declared in a function": (
        "def setup():\n    global API\n    from fastapi import FastAPI as API\n"
        'app = API(version="1")\n'
    ),
    "nonlocal declared in a nested function": (
        "def outer():\n    API = None\n    def inner():\n        nonlocal API\n"
        "        from fastapi import FastAPI as API\n"
        '    inner()\n    return API(version="1")\n'
    ),
    "rename in a class body used there": (
        'from fastapi import FastAPI\nclass C:\n    A = FastAPI\n    app = A(version="1")\n'
    ),
    "inside a lambda": 'from fastapi import FastAPI\nmake = lambda: FastAPI(version="1")\n',
    "inside a comprehension": (
        'from fastapi import FastAPI\napps = [FastAPI(version="1") for _ in range(2)]\n'
    ),
    "walrus in a comprehension binds outside it": (
        "from fastapi import FastAPI\n"
        "def f():\n    [(A := FastAPI) for _ in [1]]\n"
        '    return A(version="1")\n'
    ),
    # #2105 review: a class-body store reads the enclosing binding on its RHS.
    "class rebinds the outer name to itself": (
        'from fastapi import FastAPI as API\nclass C:\n    API = API\n    app = API(version="1")\n'
    ),
    # #2106: a class-body read of a name the class binds skips enclosing functions.
    "class rebinds a module name an enclosing function shadows": (
        "from fastapi import FastAPI as API\ndef outer():\n    API = object\n"
        '    class C:\n        API = API\n        app = API(version="1")\n'
    ),
    # #2106: a nonlocal READ resolves past a class that declares the name global.
    "nonlocal read under a class that declares global": (
        "def outer():\n    API = None\n    class C:\n        global API\n"
        "        def setup(self):\n            nonlocal API\n"
        "            from fastapi import FastAPI as API\n"
        '            return API(version="1")\n'
    ),
    # #2105 review: nonlocal skips the class and lands on the enclosing function.
    "nonlocal in a method targets the enclosing function": (
        "def outer():\n    API = None\n"
        "    class C:\n        API = object\n"
        "        def setup(self):\n            nonlocal API\n"
        "            from fastapi import FastAPI as API\n"
        '    C().setup()\n    return API(version="1")\n'
    ),
    # #2106 review: a class's `global` binds its own body, never its methods.
    "method reads past a class that declares the name global": (
        "def outer():\n    from fastapi import FastAPI as API\n"
        '    class C:\n        global API\n        def make(self):\n            return API(version="1")\n'
    ),
    # #2106 review: every function in a class body sees its implicit `__class__` cell.
    "__class__ of a FastAPI subclass": (
        "from fastapi import FastAPI\nclass C(FastAPI):\n"
        '    def make(self):\n        return __class__(version="1")\n'
    ),
    # #2106 review pass 2: a `nonlocal __class__` store writes the cell.
    "nonlocal __class__ rebinds the cell": (
        "class C:\n    def make(self):\n        nonlocal __class__\n"
        "        from fastapi import FastAPI as __class__\n"
        '        return __class__(version="1")\n'
    ),
    # #2106 review pass 2: an inlined class-body comprehension reads the module (PEP 709).
    "class-body list comprehension reads the module __class__": (
        "from fastapi import FastAPI as __class__\nclass C:\n"
        '    apps = [__class__(version="1") for _ in [0]]\n'
    ),
    "lambda in a class-body generator reads the cell": (
        "from fastapi import FastAPI\nclass C(FastAPI):\n"
        '    makers = list(lambda: __class__(version="1") for _ in [0])\n'
    ),
    # #2106 review: `__API` in class C is `_C__API`.
    "mangled private name in a class body": (
        'from fastapi import FastAPI as _C__API\nclass C:\n    app = __API(version="1")\n'
    ),
    "mangled private name in a method": (
        "from fastapi import FastAPI as _C__API\nclass C:\n"
        '    def m(self):\n        return __API(version="1")\n'
    ),
    # #2105 review: self-referential attribute rebinding must still terminate.
    "module rebound to its own submodule": (
        'import fastapi as f\nf = f.applications\napp = f.FastAPI(version="1")\n'
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
    # #2104: a binding in one scope must not leak into another.
    "import in another function": (
        "def a():\n    from fastapi import FastAPI as API\n    return API\n"
        'def b():\n    return API(version="1")\n'
    ),
    "rename in another function": (
        "from fastapi import FastAPI\n"
        "def a():\n    API = FastAPI\n    return API\n"
        'app = API(version="1")\n'
    ),
    "parameter shadows import": (
        'from fastapi import FastAPI\ndef f(FastAPI):\n    return FastAPI(version="1")\n'
    ),
    "keyword-only parameter shadows import": (
        'from fastapi import FastAPI\ndef f(*, FastAPI):\n    return FastAPI(version="1")\n'
    ),
    "lambda parameter shadows import": (
        'from fastapi import FastAPI\nmake = lambda FastAPI: FastAPI(version="1")\n'
    ),
    "local assignment shadows import": (
        "from fastapi import FastAPI\n"
        'def f():\n    FastAPI = Other\n    return FastAPI(version="1")\n'
    ),
    "local import from elsewhere shadows module": (
        "import fastapi\n"
        'def f():\n    import mylib as fastapi\n    return fastapi.FastAPI(version="1")\n'
    ),
    "parameter shadows module": (
        'import fastapi\ndef f(fastapi):\n    return fastapi.FastAPI(version="1")\n'
    ),
    "for target shadows import": (
        "from fastapi import FastAPI\n"
        'def f(makers):\n    for FastAPI in makers:\n        FastAPI(version="1")\n'
    ),
    "comprehension target shadows import": (
        'from fastapi import FastAPI\napps = [FastAPI(version="1") for FastAPI in makers]\n'
    ),
    "class body is invisible to its methods": (
        "from fastapi import FastAPI\n"
        "class C:\n    A = FastAPI\n"
        '    def m(self):\n        return A(version="1")\n'
    ),
    "attribute past the class is not a constructor": (
        'import fastapi\napp = fastapi.FastAPI.FastAPI(version="1")\n'
    ),
    # #2106: the reverse of the planted case; the class reads the module's object.
    "class rebinds a module name over an enclosing function's import": (
        "API = object\ndef outer():\n    from fastapi import FastAPI as API\n"
        '    class C:\n        API = API\n        app = API(version="1")\n'
    ),
    # #2106 review: the reverses of the planted cases.
    "method reads the enclosing function past a class's global": (
        "from fastapi import FastAPI as API\ndef outer():\n    API = object\n"
        '    class C:\n        global API\n        def make(self):\n            return API(version="1")\n'
    ),
    "module __class__ is not a method's cell": (
        "from fastapi import FastAPI as __class__\nclass C:\n"
        '    def make(self):\n        return __class__(version="1")\n'
    ),
    "class body reads the module, not its own cell": (
        'from fastapi import FastAPI\nclass C(FastAPI):\n    app = __class__(version="1")\n'
    ),
    "class-body list comprehension does not read the cell": (
        "from fastapi import FastAPI\nclass C(FastAPI):\n"
        '    apps = [__class__(version="1") for _ in [0]]\n'
    ),
    "mangled name is not the unmangled import": (
        'from fastapi import FastAPI as __API\nclass C:\n    app = __API(version="1")\n'
    ),
    "relative import named fastapi": ('from .fastapi import FastAPI\napp = FastAPI(version="1")\n'),
}


@pytest.mark.parametrize("source", DUNDER_PLANTED.values(), ids=DUNDER_PLANTED.keys())
def test_planted_dunder_is_caught(source: str) -> None:
    assert [f.shape for f in _violations_within(source, _DEADLINE_SECONDS)] == [DUNDER]


@pytest.mark.parametrize("source", FASTAPI_PLANTED.values(), ids=FASTAPI_PLANTED.keys())
def test_planted_fastapi_version_is_caught(source: str) -> None:
    assert [f.shape for f in _violations_within(source, _DEADLINE_SECONDS)] == [FASTAPI]


@pytest.mark.parametrize("source", CLEAN.values(), ids=CLEAN.keys())
def test_clean_source_is_not_flagged(source: str) -> None:
    assert _violations_within(source, _DEADLINE_SECONDS) == []


@pytest.mark.parametrize(
    "source",
    [
        "import fastapi as f\nf = f.applications\n",
        "import fastapi as f\nf = f.x\n",
        "import fastapi as a\nb = a\na = b.applications\nb = a.applications\n",
    ],
)
def test_cyclic_attribute_rebinding_terminates(source: str) -> None:
    """Before #2105 review each fixpoint pass grew ``fastapi.applications.applications...``.

    The call runs under a deadline so a non-terminating detector is a normal,
    recorded test failure within seconds rather than a hung run.
    """
    assert _violations_within(source, _DEADLINE_SECONDS) == []


_DEADLINE_SECONDS = 5.0


class _DeadlineExceededError(Exception):
    pass


def _violations_within(source: str, seconds: float) -> list[Finding]:
    """``violations(source)``, or ``pytest.fail`` when it runs past ``seconds``.

    SIGALRM interrupts the loop itself, so nothing keeps spinning afterwards.
    Off the main thread (where signals cannot be installed) a daemon thread
    and a bounded join give the same verdict.
    """
    if threading.current_thread() is threading.main_thread() and hasattr(signal, "SIGALRM"):

        def _expire(_signum: int, _frame: FrameType | None) -> None:
            raise _DeadlineExceededError

        previous = signal.signal(signal.SIGALRM, _expire)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        try:
            return violations(source)
        except _DeadlineExceededError:
            pytest.fail(f"violations() did not return within {seconds}s")
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
    found: list[list[Finding]] = []
    worker = threading.Thread(target=lambda: found.append(violations(source)), daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive() or not found:
        pytest.fail(f"violations() did not return within {seconds}s")
    return found[0]


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
