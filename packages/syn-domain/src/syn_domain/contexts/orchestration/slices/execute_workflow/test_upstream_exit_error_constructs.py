"""UpstreamExitError must construct: its MRO reaches UpstreamFailureError (#1593)."""

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    NonZeroExitError,
    UpstreamExitError,
)
from syn_shared.upstream_failure import UpstreamFailureError, UpstreamFailureKind


@pytest.mark.unit
def test_upstream_exit_error_carries_both_its_exit_code_and_its_upstream_kind() -> None:
    kind = next(iter(UpstreamFailureKind))
    error = UpstreamExitError("codex at capacity", exit_code=1, upstream_kind=kind)

    assert str(error) == "codex at capacity"
    assert error.exit_code == 1
    assert error.upstream_kind is kind
    assert isinstance(error, NonZeroExitError)
    assert isinstance(error, UpstreamFailureError)
