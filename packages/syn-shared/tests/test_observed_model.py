"""The observed-vs-requested contract (ADR-067): aliases are requests, never models."""

from __future__ import annotations

import pytest

from syn_shared.agents import CodexModelAlias, ModelAlias, ModelId
from syn_shared.observed_model import (
    LEGACY_REQUESTED_ALIASES,
    UNKNOWN_MODEL_KEY,
    RecordedModel,
    format_cost_model_key,
    format_observed_model,
    split_observation_model,
    split_recorded_model,
)

pytestmark = pytest.mark.unit

_ALL_ALIASES = sorted({*ModelAlias, *CodexModelAlias})


class TestLegacyRows:
    @pytest.mark.parametrize("alias", _ALL_ALIASES)
    def test_legacy_alias_is_a_request_not_a_model(self, alias: str) -> None:
        got = split_observation_model({"model": alias})
        assert got == RecordedModel(observed=None, requested=alias)
        assert got.cost_key == UNKNOWN_MODEL_KEY

    def test_legacy_explicit_id_is_kept_as_observed(self) -> None:
        got = split_observation_model({"model": ModelId.CLAUDE_OPUS_5})
        assert got == RecordedModel(observed=ModelId.CLAUDE_OPUS_5, requested=None)

    def test_legacy_row_without_model(self) -> None:
        assert split_observation_model({}) == RecordedModel(observed=None, requested=None)

    def test_every_current_alias_is_in_the_frozen_legacy_set(self) -> None:
        # Every alias that existed when the contract landed. A NEW alias must
        # not be added to the frozen set (post-contract rows carry the key).
        assert set(_ALL_ALIASES) <= LEGACY_REQUESTED_ALIASES


class TestPostContractRows:
    def test_fields_taken_as_written(self) -> None:
        got = split_observation_model({"model": "claude-opus-5-5", "requested_model": "opus"})
        assert got == RecordedModel(observed="claude-opus-5-5", requested="opus")
        assert got.cost_key == "claude-opus-5-5"
        assert got.pricing_model == "claude-opus-5-5"

    def test_null_requested_key_still_marks_post_contract(self) -> None:
        got = split_observation_model({"model": None, "requested_model": None})
        assert got == RecordedModel(observed=None, requested=None)

    def test_unreported_model_prices_at_request_but_keys_unknown(self) -> None:
        got = split_observation_model({"model": None, "requested_model": "gpt-sol"})
        assert got.cost_key == UNKNOWN_MODEL_KEY
        assert got.pricing_model == "gpt-sol"

    @pytest.mark.parametrize("alias", _ALL_ALIASES)
    def test_alias_in_model_is_demoted_even_post_contract(self, alias: str) -> None:
        got = split_recorded_model(alias, None, has_requested_key=True)
        assert got.observed is None
        assert got.requested == alias


class TestDisplay:
    def test_observed_is_verbatim(self) -> None:
        assert format_observed_model("claude-opus-5-5", "opus") == "claude-opus-5-5"

    def test_unknown_with_request(self) -> None:
        assert format_observed_model(None, "gpt-sol") == "unknown (requested: gpt-sol)"

    def test_unknown(self) -> None:
        assert format_observed_model(None, None) == "unknown"

    def test_cost_key(self) -> None:
        assert format_cost_model_key(UNKNOWN_MODEL_KEY) == "unknown"
        assert format_cost_model_key("gpt-6-sol") == "gpt-6-sol"
