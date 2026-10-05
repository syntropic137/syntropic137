"""check_complexity_thresholds.py must measure exactly what APS measures (#1585).

The script is only worth running first if a green from it predicts a green
from `fitness-check`, and a red predicts a red. So these tests run the aps
binary itself and compare every Python measurement, not a sample: the whole
tree, and a fixture with one module over 750 LOC and one function over
cyclomatic 10.

They need the binary `just aps-build` produces, and skip, saying so, without
it, which is what the unit job sees. `fitness-check` builds it and runs them
with SYN_REQUIRE_APS=1, where a missing binary FAILS instead: that is the PR
gate (CI's `just preflight`, and `preflight-agent` via fitness-agent) that
proves the early check still agrees with APS.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_complexity_thresholds import find_violations, measure

_ROOT = Path(__file__).resolve().parents[2]
_APS = _ROOT / "lib/agent-paradise-standards-system/target/release/apss-dev"

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def needs_aps() -> None:
    if _APS.exists():
        return
    reason = f"no aps binary at {_APS}; run `just aps-build`"
    if os.environ.get("SYN_REQUIRE_APS") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


def _aps_measurements(root: Path, out: Path) -> Counter[tuple[str, str, int]]:
    """What APS's topology analyzer records for Python under `root`."""
    subprocess.run(
        [str(_APS), "run", "code-topology", "analyze", ".", "--output", str(out), "--seed", "42"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    functions = json.loads((out / "metrics/functions.json").read_text())["functions"]
    modules = json.loads((out / "metrics/modules.json").read_text())["modules"]
    found: Counter[tuple[str, str, int]] = Counter()
    for f in functions:
        if f["id"].startswith("python:"):
            found["max-cyclomatic", f["id"], f["metrics"]["cyclomatic"]] += 1
    for m in modules:
        if m["languages"] == ["python"]:
            found["max-loc-file", m["id"], m["metrics"]["lines_of_code"]] += 1
    return found


def _ours(root: Path) -> Counter[tuple[str, str, int]]:
    return Counter((m.rule, m.entity, m.value) for m in measure(root))


def _over_limit_fixture(root: Path) -> None:
    for name in ("fitness.toml", "fitness-exceptions.toml"):
        shutil.copy(_ROOT / name, root / name)
    pkg = root / "apps" / "fixture"
    pkg.mkdir(parents=True)
    body = "".join(f"    x{i} = {i}\n" for i in range(760))
    (pkg / "big.py").write_text(f"def long_one():\n{body}    return x0\n")
    branches = "".join(f"    if x == {i}:\n        return {i}\n" for i in range(10))
    (pkg / "tangled.py").write_text(f"def eleven(x):\n{branches}    return -1\n")


# Every decision node the Python grammar counts, plus the ones it ignores
# (finally, raise, and `except*` handlers, which are not `except_clause`), the
# elif/else-if distinction, and nesting.
_SHAPES = """
def shapes(a, b=1 if True else 2) -> int:
    if a and b or a:
        pass
    elif b:
        pass
    else:
        if a:
            pass
    for x in a:
        pass
    else:
        pass
    while a:
        break
    try:
        pass
    except ValueError:
        pass
    except TypeError:
        pass
    else:
        pass
    finally:
        if a:
            pass
    match a:
        case 1:
            pass
        case _:
            pass
    assert a
    raise ValueError(1 if a else 2)
    y = [i for i in a if i]
    z = {i for i in a if i}
    def inner():
        return a if b else lambda: a and b
    return 0


def groups(a) -> int:
    try:
        pass
    except* E0:
        pass
    except* E1:
        pass
    except* E2:
        pass
    except* E3:
        pass
    except* E4:
        pass
    except* E5:
        pass
    except* E6:
        pass
    except* E7:
        pass
    except* E8:
        pass
    except* E9:
        pass
    else:
        pass
    return 0
"""


def test_every_python_measurement_matches_aps_on_this_tree(tmp_path: Path) -> None:
    ours, theirs = _ours(_ROOT), _aps_measurements(_ROOT, tmp_path / "topology")
    assert ours - theirs == Counter() and theirs - ours == Counter(), (
        f"only ours: {sorted((ours - theirs).elements())[:20]}\n"
        f"only APS: {sorted((theirs - ours).elements())[:20]}"
    )
    assert find_violations(_ROOT) == [], "APS fitness-check passes on main, so this must too"


def test_the_over_limit_fixture_fails_both_ways(tmp_path: Path) -> None:
    _over_limit_fixture(tmp_path)
    (tmp_path / "apps/fixture/shapes.py").write_text(_SHAPES)
    assert _ours(tmp_path) == _aps_measurements(tmp_path, tmp_path / ".topology")
    report = tmp_path / "report.json"
    aps = subprocess.run(
        [str(_APS), "run", "architecture-fitness", "validate", ".", "--report", str(report)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert aps.returncode != 0, aps.stdout
    flagged = {(v.measurement.rule, v.measurement.entity) for v in find_violations(tmp_path)}
    assert flagged == {
        ("max-loc-file", "apps.fixture.big"),
        ("max-cyclomatic", "python:apps.fixture.tangled::eleven"),
        ("max-cyclomatic", "python:apps.fixture.shapes::shapes"),
    }
    report_text = report.read_text()
    for _rule, entity in flagged:
        assert entity in report_text, f"APS did not flag {entity}"
