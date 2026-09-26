"""`get_controller()` must actually build, not just typecheck.

A cross-model review of #1452 found the shipped code broken in production
while every test passed: `_wiring.get_controller()` still imported
`ProjectionControlStateAdapter` - a module that PR deletes - and still passed
the removed `state_port=` argument. Every control route and the execution
handler that calls it would have failed at construction.

The tests did not catch it because they all build `ExecutionController`
directly with their own fakes. That is the right way to test admission logic
and the wrong way to learn whether the application can start, and the gap
between those two is exactly where a deletion hides.

So this test asserts the thing no unit test was asserting: the real factory,
with the real wiring, returns an object.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_get_controller_constructs() -> None:
    from syn_api._wiring import get_controller

    controller = get_controller()
    assert controller is not None


def test_the_controller_holds_an_execution_repository_not_a_state_port() -> None:
    """The shape of the fix, asserted where wiring can break it.

    `_state_port` is the projection-backed attribute whose staleness was the
    fail-open. Its absence is what makes lag structurally impossible rather
    than merely unlikely, so a wiring change that reintroduced it would undo
    ADR-014 section 7 fail-open 1 while the admission tests kept passing.
    """
    from syn_api._wiring import get_controller

    controller = get_controller()
    executions = getattr(controller, "_executions", None)
    # PRESENT AND USABLE, not merely present. The first version of this test
    # asserted `hasattr`, and a mutation passing `executions=None` through the
    # wiring still set the attribute - so the test passed while the controller
    # could not load an aggregate at all. `hasattr` on an injected dependency
    # says nothing about whether the dependency exists.
    assert executions is not None, (
        "the controller is not holding an execution repository, so it cannot "
        "ask the aggregate and must be deciding from something else"
    )
    assert hasattr(executions, "get_by_id"), (
        f"the controller's repository is a {type(executions).__name__}, which "
        "cannot rehydrate an aggregate"
    )
    assert not hasattr(controller, "_state_port"), (
        "a control state port is back on the controller; admission can once "
        "again be decided from a projection that lags the stream"
    )


def test_it_is_a_singleton() -> None:
    """Two calls must not build two controllers over one signal queue."""
    from syn_api._wiring import get_controller

    assert get_controller() is get_controller()
