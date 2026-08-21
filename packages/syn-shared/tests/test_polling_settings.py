"""Polling settings, and why workflow concurrency defaults to one.

The default here is not a performance tuning choice. It is a safety one, and
it is temporary: see #865.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from syn_shared.settings.polling import (
    ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES,
    PollingSettings,
)


@pytest.mark.unit
class TestConcurrencyIsSafeByDefault:
    """#865: concurrent executions are not isolated from each other.

    The processor keeps per-execution state on an instance they share, so two
    concurrent runs read each other's inputs and one execution's cancellation
    tears down the others' containers. Until that is fixed the safe value has
    to be the DEFAULT rather than a documented recommendation: the inputs
    failure is silent, and a silent wrong result is worse than a slow correct
    one.
    """

    def test_the_default_runs_one_execution_at_a_time(self) -> None:
        assert PollingSettings().max_concurrent_dispatches == 1

    def test_an_operator_can_still_raise_it(self) -> None:
        """Deliberately not forbidden. A known-risk choice, not a lock."""
        with patch.dict(os.environ, {"SYN_POLLING_MAX_CONCURRENT_DISPATCHES": "5"}):
            assert PollingSettings().max_concurrent_dispatches == 5

    def test_the_env_name_matches_the_prefixed_field(self) -> None:
        """The constant exists so a diagnostic can name the var, not a literal."""
        assert ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES == "SYN_POLLING_MAX_CONCURRENT_DISPATCHES"


@pytest.mark.unit
class TestTheEnvNameIsTheOnePydanticReads:
    """The constant is bound as `validation_alias`, not kept in step by hand.

    An earlier version declared the name twice - once as a constant for the
    diagnostic to print, once implicitly via `env_prefix` - and a comment
    admitting they had to stay synchronized. A name that has to be maintained
    in two places is a name that will eventually disagree with itself.
    """

    def test_setting_the_constant_named_variable_changes_the_field(self) -> None:
        with patch.dict(os.environ, {ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES: "7"}, clear=False):
            assert PollingSettings().max_concurrent_dispatches == 7
