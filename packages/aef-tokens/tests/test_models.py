"""Tests for token and budget models."""

import pytest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aef_tokens.models import (
    DEFAULT_BUDGETS,
    ScopedToken,
    SpendBudget,
    TokenScope,
    TokenType,
    WorkflowType,
)


@pytest.mark.unit
class TestTokenScope:
    """Tests for TokenScope."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        scope = TokenScope()
        assert scope.allowed_apis == []
        assert scope.allowed_repos == []
        assert scope.max_input_tokens == 100_000
        assert scope.max_output_tokens == 50_000
        assert scope.max_cost_usd == Decimal("10.00")

    def test_to_dict(self) -> None:
        """Should serialize to dict."""
        scope = TokenScope(
            allowed_apis=["anthropic:messages"],
            allowed_repos=["org/repo"],
            max_cost_usd=Decimal("5.00"),
        )
        data = scope.to_dict()

        assert data["allowed_apis"] == ["anthropic:messages"]
        assert data["allowed_repos"] == ["org/repo"]
        assert data["max_cost_usd"] == "5.00"

    def test_from_dict(self) -> None:
        """Should deserialize from dict."""
        data = {
            "allowed_apis": ["github:contents"],
            "allowed_repos": ["a/b", "c/d"],
            "max_input_tokens": 50000,
            "max_output_tokens": 25000,
            "max_cost_usd": "20.00",
        }
        scope = TokenScope.from_dict(data)

        assert scope.allowed_apis == ["github:contents"]
        assert len(scope.allowed_repos) == 2
        assert scope.max_cost_usd == Decimal("20.00")


class TestScopedToken:
    """Tests for ScopedToken."""

    def test_is_expired_when_past(self) -> None:
        """Should be expired when past expiry time."""
        token = ScopedToken(
            token_id="test-123",
            token_type=TokenType.ANTHROPIC,
            execution_id="exec-456",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
            scope=TokenScope(),
        )
        assert token.is_expired is True

    def test_is_not_expired_when_future(self) -> None:
        """Should not be expired when before expiry time."""
        token = ScopedToken(
            token_id="test-123",
            token_type=TokenType.ANTHROPIC,
            execution_id="exec-456",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            scope=TokenScope(),
        )
        assert token.is_expired is False

    def test_ttl_seconds(self) -> None:
        """Should calculate TTL correctly."""
        expires_in = 300  # 5 minutes
        token = ScopedToken(
            token_id="test-123",
            token_type=TokenType.ANTHROPIC,
            execution_id="exec-456",
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
            scope=TokenScope(),
        )
        # Allow 1 second tolerance
        assert abs(token.ttl_seconds - expires_in) <= 1

    def test_ttl_seconds_never_negative(self) -> None:
        """TTL should be 0 when expired."""
        token = ScopedToken(
            token_id="test-123",
            token_type=TokenType.ANTHROPIC,
            execution_id="exec-456",
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
            scope=TokenScope(),
        )
        assert token.ttl_seconds == 0

    def test_serialization_roundtrip(self) -> None:
        """Should serialize and deserialize correctly."""
        original = ScopedToken(
            token_id="test-123",
            token_type=TokenType.GITHUB,
            execution_id="exec-456",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scope=TokenScope(allowed_repos=["org/repo"]),
        )

        data = original.to_dict()
        restored = ScopedToken.from_dict(data)

        assert restored.token_id == original.token_id
        assert restored.token_type == original.token_type
        assert restored.execution_id == original.execution_id
        assert restored.scope.allowed_repos == original.scope.allowed_repos


class TestSpendBudget:
    """Tests for SpendBudget."""

    def test_remaining_calculations(self) -> None:
        """Should calculate remaining budget correctly."""
        budget = SpendBudget(
            execution_id="exec-123",
            workflow_type=WorkflowType.RESEARCH,
            max_input_tokens=100_000,
            max_output_tokens=50_000,
            max_cost_usd=Decimal("10.00"),
            used_input_tokens=30_000,
            used_output_tokens=15_000,
            used_cost_usd=Decimal("3.50"),
        )

        assert budget.remaining_input_tokens == 70_000
        assert budget.remaining_output_tokens == 35_000
        assert budget.remaining_cost_usd == Decimal("6.50")

    def test_usage_percent(self) -> None:
        """Should calculate usage percentages correctly."""
        budget = SpendBudget(
            execution_id="exec-123",
            workflow_type=WorkflowType.RESEARCH,
            max_input_tokens=100_000,
            max_output_tokens=50_000,
            max_cost_usd=Decimal("10.00"),
            used_input_tokens=80_000,
            used_output_tokens=25_000,
            used_cost_usd=Decimal("8.00"),
        )

        assert budget.input_usage_percent == 80.0
        assert budget.output_usage_percent == 50.0
        assert budget.cost_usage_percent == 80.0

    def test_is_exhausted_by_input_tokens(self) -> None:
        """Should be exhausted when input tokens exceeded."""
        budget = SpendBudget(
            execution_id="exec-123",
            workflow_type=WorkflowType.RESEARCH,
            max_input_tokens=100_000,
            max_output_tokens=50_000,
            max_cost_usd=Decimal("10.00"),
            used_input_tokens=100_000,
        )
        assert budget.is_exhausted is True

    def test_is_exhausted_by_cost(self) -> None:
        """Should be exhausted when cost exceeded."""
        budget = SpendBudget(
            execution_id="exec-123",
            workflow_type=WorkflowType.RESEARCH,
            max_input_tokens=100_000,
            max_output_tokens=50_000,
            max_cost_usd=Decimal("10.00"),
            used_cost_usd=Decimal("10.00"),
        )
        assert budget.is_exhausted is True

    def test_can_afford(self) -> None:
        """Should check if request is affordable."""
        budget = SpendBudget(
            execution_id="exec-123",
            workflow_type=WorkflowType.RESEARCH,
            max_input_tokens=100_000,
            max_output_tokens=50_000,
            max_cost_usd=Decimal("10.00"),
            used_input_tokens=90_000,
            used_cost_usd=Decimal("9.00"),
        )

        # Can afford small request
        assert budget.can_afford(5_000, 2_000, Decimal("0.50")) is True

        # Cannot afford request that exceeds input tokens
        assert budget.can_afford(15_000, 2_000, Decimal("0.50")) is False

        # Cannot afford request that exceeds cost
        assert budget.can_afford(5_000, 2_000, Decimal("2.00")) is False

    def test_for_workflow(self) -> None:
        """Should create budget with workflow defaults."""
        budget = SpendBudget.for_workflow("exec-123", WorkflowType.IMPLEMENTATION)

        expected = DEFAULT_BUDGETS[WorkflowType.IMPLEMENTATION]
        assert budget.max_input_tokens == expected["max_input_tokens"]
        assert budget.max_output_tokens == expected["max_output_tokens"]
        assert budget.max_cost_usd == expected["max_cost_usd"]

    def test_serialization_roundtrip(self) -> None:
        """Should serialize and deserialize correctly."""
        original = SpendBudget(
            execution_id="exec-123",
            workflow_type=WorkflowType.REVIEW,
            max_input_tokens=50_000,
            max_output_tokens=20_000,
            max_cost_usd=Decimal("5.00"),
            used_input_tokens=10_000,
            used_output_tokens=5_000,
            used_cost_usd=Decimal("1.25"),
        )

        data = original.to_dict()
        restored = SpendBudget.from_dict(data)

        assert restored.execution_id == original.execution_id
        assert restored.workflow_type == original.workflow_type
        assert restored.max_input_tokens == original.max_input_tokens
        assert restored.used_cost_usd == original.used_cost_usd
