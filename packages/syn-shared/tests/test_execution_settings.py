"""The execution budget setting: one name, one limit, sized against memory (#1557)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from syn_shared.env_constants import (
    ENV_SYN_EXECUTION_MAX_CONCURRENT,
    ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES,
)
from syn_shared.settings.execution import (
    API_MEMORY_FLOOR_EXECUTIONS,
    DEFAULT_MAX_CONCURRENT_EXECUTIONS,
    ExecutionSettings,
    api_memory_limit_for,
    executions_that_fit,
)
from syn_shared.settings.infra import InfraSettings
from syn_shared.settings.polling import PollingSettings

pytestmark = pytest.mark.unit


class TestTheDefaultFitsTheDefaultApiMemoryLimit:
    """#1552: 8 concurrent runs OOM-killed an API at the 512m default."""

    def test_the_default_is_what_512m_holds(self) -> None:
        assert ExecutionSettings().max_concurrent == DEFAULT_MAX_CONCURRENT_EXECUTIONS
        assert executions_that_fit(512) == DEFAULT_MAX_CONCURRENT_EXECUTIONS

    def test_the_incident_concurrency_does_not_fit_512m(self) -> None:
        assert executions_that_fit(512) < 8

    def test_a_bigger_limit_holds_more(self) -> None:
        assert executions_that_fit(2048) == 20

    def test_a_tiny_limit_still_runs_one(self) -> None:
        assert executions_that_fit(64) == 1


def _mib(limit: str) -> int:
    """Docker's memory notation (``3200m``, ``2g``) in MiB."""
    unit = {"m": 1, "g": 1024}[limit[-1]]
    return int(limit[:-1]) * unit


class TestTheApiMemoryDefaultIsDerivedFromConcurrency:
    """#1552 item 1: the API memory default holds the budget's worth of executions."""

    def test_the_generated_default_holds_the_default_budget(self) -> None:
        # The consumer: the InfraSettings field that infra/.env.example and the
        # compose fallback are generated from and checked against.
        default = InfraSettings.model_fields["api_memory_limit"].default

        assert default == api_memory_limit_for(DEFAULT_MAX_CONCURRENT_EXECUTIONS)
        assert executions_that_fit(_mib(default)) >= DEFAULT_MAX_CONCURRENT_EXECUTIONS

    def test_a_budget_above_the_floor_raises_the_limit(self) -> None:
        # 32 is past the floor, so only a derivation that reads the budget
        # can produce a limit that holds it.
        limit = api_memory_limit_for(32)

        assert limit == "3200m"
        assert executions_that_fit(_mib(limit)) == 32

    def test_each_execution_past_the_floor_costs_its_allowance(self) -> None:
        above = API_MEMORY_FLOOR_EXECUTIONS + 1

        assert _mib(api_memory_limit_for(above + 1)) - _mib(api_memory_limit_for(above)) == 96

    def test_the_default_budget_does_not_derive_the_limit_that_oomed(self) -> None:
        # 128 + 4 x 96 = 512MiB is exactly what #1552 was killed at.
        assert _mib(api_memory_limit_for(DEFAULT_MAX_CONCURRENT_EXECUTIONS)) > 512
        assert api_memory_limit_for(DEFAULT_MAX_CONCURRENT_EXECUTIONS) == "2g"

    def test_the_floor_holds_the_north_star_tier(self) -> None:
        assert executions_that_fit(_mib(api_memory_limit_for(1))) == API_MEMORY_FLOOR_EXECUTIONS


class TestTheEnvNameIsTheOnePydanticReads:
    def test_the_field_is_bound_to_the_constant(self) -> None:
        field = ExecutionSettings.model_fields["max_concurrent"]
        assert field.validation_alias == ENV_SYN_EXECUTION_MAX_CONCURRENT
        assert ENV_SYN_EXECUTION_MAX_CONCURRENT == "SYN_EXECUTION_MAX_CONCURRENT"

    def test_setting_it_changes_the_field(self) -> None:
        with patch.dict(os.environ, {ENV_SYN_EXECUTION_MAX_CONCURRENT: "7"}, clear=False):
            assert ExecutionSettings().max_concurrent == 7

    def test_zero_is_refused(self) -> None:
        with (
            patch.dict(os.environ, {ENV_SYN_EXECUTION_MAX_CONCURRENT: "0"}, clear=False),
            pytest.raises(ValueError, match="greater than or equal to 1"),
        ):
            ExecutionSettings()


class TestTheRetiredNameDoesNothing:
    """It bounded trigger and resume starts but never direct ones; #1557 retired it.

    Honouring it would bring back a per-path limit, and at its old value of 1 it
    is exactly what serialised five resumes behind one running child.
    """

    def test_it_does_not_set_the_budget(self) -> None:
        with patch.dict(os.environ, {ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES: "1"}, clear=False):
            assert ExecutionSettings().max_concurrent == DEFAULT_MAX_CONCURRENT_EXECUTIONS

    def test_polling_no_longer_has_a_concurrency_field(self) -> None:
        assert "max_concurrent_dispatches" not in PollingSettings.model_fields
