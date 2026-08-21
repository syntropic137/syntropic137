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

    def test_the_field_is_bound_to_the_constant_itself(self) -> None:
        """Pins the BINDING, not just the behaviour.

        The alias string currently equals `env_prefix` + field name, so
        removing `validation_alias` entirely changes nothing an operator can
        observe - and every behavioural test here stays green. That is the
        "passes for the wrong reason" shape: the tests would keep agreeing
        while the constant quietly stopped being what pydantic reads.

        Asserting the declared alias is the only check that fails when the
        binding is dropped.
        """
        field = PollingSettings.model_fields["max_concurrent_dispatches"]

        assert field.validation_alias == ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES

    @pytest.mark.parametrize(
        "wrong_name",
        ["MAX_CONCURRENT_DISPATCHES", "max_concurrent_dispatches", "SYN_MAX_CONCURRENT"],
        ids=["unprefixed", "lowercase", "wrong-prefix"],
    )
    def test_no_other_name_is_accepted(self, wrong_name: str) -> None:
        """Exactly one spelling, so the alias cannot become a second footgun.

        Binding `validation_alias` replaces the `env_prefix` derivation for
        this field rather than adding to it. Worth pinning: an alias that
        ALSO left a prefix-derived name working would mean two ways to set one
        value, and eventually two values.
        """
        with patch.dict(os.environ, {wrong_name: "9"}, clear=False):
            assert PollingSettings().max_concurrent_dispatches == 1

    def test_sibling_fields_still_use_the_prefix(self) -> None:
        """The alias is scoped to one field and does not disturb the others."""
        with patch.dict(os.environ, {"SYN_POLLING_MAX_DISPATCHES_PER_HOUR": "13"}, clear=False):
            assert PollingSettings().max_dispatches_per_hour == 13

    def test_setting_the_constant_named_variable_changes_the_field(self) -> None:
        with patch.dict(os.environ, {ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES: "7"}, clear=False):
            assert PollingSettings().max_concurrent_dispatches == 7
