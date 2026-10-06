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
    DEFAULT_MAX_CONCURRENT_EXECUTIONS,
    ExecutionSettings,
    executions_that_fit,
)
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
