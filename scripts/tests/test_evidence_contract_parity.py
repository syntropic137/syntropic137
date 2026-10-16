"""An evidence request the contract accepts is one the mutation workflow accepts.

`EvidenceRequest` (syn_domain) restates `scripts/mutation_evidence.py`'s input
rules as a pattern rather than importing a CLI script into the domain. Two
definitions drift silently, so this drives both validators over the same
selections: every selection the model takes, `parse_tests` must take too. The
model may be stricter; it may never be looser.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from scripts import mutation_evidence as me
from scripts.mutation_evidence import InputError, parse_tests

from syn_domain.contexts.orchestration._shared import evidence_contract as contract
from syn_domain.contexts.orchestration._shared.evidence_contract import EvidenceRequest

pytestmark = pytest.mark.unit

_GOOD = "packages/x/test_y.py::TestZ::test_w[case-1]"

_NODE_IDS = [
    _GOOD,
    "test_x.py",
    "tests/test_x.py::test_ok",
    "tests/a.b/test_x.py::test_ok",
    "tests/a-b/test_x.py::test_ok[p=1,q+2]",
    "tests/../test_x.py::test_ok",
    "tests/./test_x.py::test_ok",
    "tests//test_x.py::test_ok",
    "tests/.git/test_x.py::test_ok",
    "tests/-x/test_x.py::test_ok",
    "tests/.hidden/test_x.py::test_ok",
    "./tests/test_x.py::test_ok",
    "/tests/test_x.py::test_ok",
    "tests/test_x.py/::test_ok",
    "tests\\test_x.py::test_ok",
    "-x/test_x.py",
    "tests/test_x.py --pdb",
]

# Each id alone, and each in the second position behind a good one.
_SELECTIONS = [pytest.param((n,), id=f"only:{n}") for n in _NODE_IDS] + [
    pytest.param((_GOOD, n), id=f"second:{n}") for n in _NODE_IDS if n != _GOOD
]


def _model_accepts(tests: tuple[str, ...]) -> bool:
    try:
        EvidenceRequest(
            kind=contract.EvidenceKind.MUTATION,
            repository="syntropic137/syntropic137",
            branch="feat/x",
            pr=1,
            head_sha="a" * 40,
            tests=tests,
        )
    except ValidationError:
        return False
    return True


def _workflow_accepts(tests: tuple[str, ...]) -> bool:
    try:
        parse_tests(" ".join(tests))
    except InputError:
        return False
    return True


@pytest.mark.parametrize("tests", _SELECTIONS)
def test_the_model_is_never_looser_than_the_workflow(tests: tuple[str, ...]) -> None:
    if _model_accepts(tests):
        assert _workflow_accepts(tests), f"the contract accepts {tests} but the workflow refuses it"


def test_the_corpus_exercises_both_sides() -> None:
    # A parity check whose every case is refused by the model proves nothing.
    accepted = [s for s in _NODE_IDS if _model_accepts((s,))]
    assert len(accepted) >= 5
    assert len(accepted) < len(_NODE_IDS)


def test_the_limit_is_the_same() -> None:
    assert contract.MAX_TESTS == me.MAX_TESTS
