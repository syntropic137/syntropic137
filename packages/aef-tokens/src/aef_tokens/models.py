"""Data models for token vending and spend tracking.

These models define the structure of tokens and budgets used
throughout the secure token architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum


class TokenType(str, Enum):
    """Type of token being vended."""

    ANTHROPIC = "anthropic"
    GITHUB = "github"
    INTERNAL = "internal"


class WorkflowType(str, Enum):
    """Workflow type for budget allocation."""

    RESEARCH = "research"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    QUICK_FIX = "quick_fix"
    CUSTOM = "custom"


# Default budgets per workflow type
DEFAULT_BUDGETS: dict[WorkflowType, dict[str, int | Decimal]] = {
    WorkflowType.RESEARCH: {
        "max_input_tokens": 100_000,
        "max_output_tokens": 50_000,
        "max_cost_usd": Decimal("10.00"),
    },
    WorkflowType.IMPLEMENTATION: {
        "max_input_tokens": 500_000,
        "max_output_tokens": 200_000,
        "max_cost_usd": Decimal("50.00"),
    },
    WorkflowType.REVIEW: {
        "max_input_tokens": 50_000,
        "max_output_tokens": 20_000,
        "max_cost_usd": Decimal("5.00"),
    },
    WorkflowType.QUICK_FIX: {
        "max_input_tokens": 10_000,
        "max_output_tokens": 5_000,
        "max_cost_usd": Decimal("1.00"),
    },
    WorkflowType.CUSTOM: {
        "max_input_tokens": 100_000,
        "max_output_tokens": 50_000,
        "max_cost_usd": Decimal("10.00"),
    },
}


@dataclass
class TokenScope:
    """Scope restrictions for a vended token.

    Defines what APIs and resources a token can access,
    plus spend limits for that token's usage.

    Attributes:
        allowed_apis: List of allowed API endpoints (e.g., ["anthropic:messages"])
        allowed_repos: List of allowed GitHub repos (e.g., ["org/repo"])
        max_input_tokens: Maximum input tokens for this token's usage
        max_output_tokens: Maximum output tokens for this token's usage
        max_cost_usd: Maximum spend allowed for this token
    """

    allowed_apis: list[str] = field(default_factory=list)
    allowed_repos: list[str] = field(default_factory=list)
    max_input_tokens: int = 100_000
    max_output_tokens: int = 50_000
    max_cost_usd: Decimal = Decimal("10.00")

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "allowed_apis": self.allowed_apis,
            "allowed_repos": self.allowed_repos,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_cost_usd": str(self.max_cost_usd),
        }

    @classmethod
    def from_dict(cls, data: dict) -> TokenScope:
        """Create from dictionary."""
        return cls(
            allowed_apis=data.get("allowed_apis", []),
            allowed_repos=data.get("allowed_repos", []),
            max_input_tokens=data.get("max_input_tokens", 100_000),
            max_output_tokens=data.get("max_output_tokens", 50_000),
            max_cost_usd=Decimal(data.get("max_cost_usd", "10.00")),
        )


@dataclass
class ScopedToken:
    """A short-lived, scoped token for agent operations.

    These tokens are issued by the TokenVendingService and have:
    - Short TTL (default 5 minutes)
    - Scoped permissions (specific APIs, repos)
    - Spend limits

    Attributes:
        token_id: Unique identifier for this token
        token_type: Type of token (anthropic, github, internal)
        execution_id: The execution this token is for
        expires_at: When the token expires (UTC)
        scope: Scope restrictions for this token
        created_at: When the token was created (UTC)
    """

    token_id: str
    token_type: TokenType
    execution_id: str
    expires_at: datetime
    scope: TokenScope
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_expired(self) -> bool:
        """Check if token is expired."""
        return datetime.now(UTC) >= self.expires_at

    @property
    def seconds_until_expiry(self) -> float:
        """Seconds until token expires (negative if expired)."""
        now = datetime.now(UTC)
        return (self.expires_at - now).total_seconds()

    @property
    def ttl_seconds(self) -> int:
        """TTL in seconds for Redis storage."""
        return max(0, int(self.seconds_until_expiry))

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "token_id": self.token_id,
            "token_type": self.token_type.value,
            "execution_id": self.execution_id,
            "expires_at": self.expires_at.isoformat(),
            "scope": self.scope.to_dict(),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ScopedToken:
        """Create from dictionary."""
        return cls(
            token_id=data["token_id"],
            token_type=TokenType(data["token_type"]),
            execution_id=data["execution_id"],
            expires_at=datetime.fromisoformat(data["expires_at"]),
            scope=TokenScope.from_dict(data["scope"]),
            created_at=datetime.fromisoformat(data["created_at"]),
        )


@dataclass
class SpendBudget:
    """Budget allocated for an execution.

    Tracks both limits and current usage for an execution.
    All spend tracking is atomic via Redis.

    Attributes:
        execution_id: The execution this budget is for
        workflow_type: Type of workflow (affects default limits)
        max_input_tokens: Maximum input tokens allowed
        max_output_tokens: Maximum output tokens allowed
        max_cost_usd: Maximum cost allowed in USD
        used_input_tokens: Input tokens used so far
        used_output_tokens: Output tokens used so far
        used_cost_usd: Cost incurred so far in USD
        created_at: When the budget was created
    """

    execution_id: str
    workflow_type: WorkflowType
    max_input_tokens: int
    max_output_tokens: int
    max_cost_usd: Decimal
    used_input_tokens: int = 0
    used_output_tokens: int = 0
    used_cost_usd: Decimal = Decimal("0")
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def remaining_input_tokens(self) -> int:
        """Remaining input token budget."""
        return max(0, self.max_input_tokens - self.used_input_tokens)

    @property
    def remaining_output_tokens(self) -> int:
        """Remaining output token budget."""
        return max(0, self.max_output_tokens - self.used_output_tokens)

    @property
    def remaining_cost_usd(self) -> Decimal:
        """Remaining cost budget in USD."""
        return max(Decimal("0"), self.max_cost_usd - self.used_cost_usd)

    @property
    def input_usage_percent(self) -> float:
        """Input token usage as percentage."""
        if self.max_input_tokens == 0:
            return 100.0
        return (self.used_input_tokens / self.max_input_tokens) * 100

    @property
    def output_usage_percent(self) -> float:
        """Output token usage as percentage."""
        if self.max_output_tokens == 0:
            return 100.0
        return (self.used_output_tokens / self.max_output_tokens) * 100

    @property
    def cost_usage_percent(self) -> float:
        """Cost usage as percentage."""
        if self.max_cost_usd == 0:
            return 100.0
        return float((self.used_cost_usd / self.max_cost_usd) * 100)

    @property
    def is_exhausted(self) -> bool:
        """Check if any budget limit is exceeded."""
        return (
            self.used_input_tokens >= self.max_input_tokens
            or self.used_output_tokens >= self.max_output_tokens
            or self.used_cost_usd >= self.max_cost_usd
        )

    def can_afford(self, input_tokens: int, output_tokens: int, cost_usd: Decimal) -> bool:
        """Check if budget can afford a request."""
        return (
            self.used_input_tokens + input_tokens <= self.max_input_tokens
            and self.used_output_tokens + output_tokens <= self.max_output_tokens
            and self.used_cost_usd + cost_usd <= self.max_cost_usd
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "execution_id": self.execution_id,
            "workflow_type": self.workflow_type.value,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_cost_usd": str(self.max_cost_usd),
            "used_input_tokens": self.used_input_tokens,
            "used_output_tokens": self.used_output_tokens,
            "used_cost_usd": str(self.used_cost_usd),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> SpendBudget:
        """Create from dictionary."""
        return cls(
            execution_id=data["execution_id"],
            workflow_type=WorkflowType(data["workflow_type"]),
            max_input_tokens=data["max_input_tokens"],
            max_output_tokens=data["max_output_tokens"],
            max_cost_usd=Decimal(data["max_cost_usd"]),
            used_input_tokens=data.get("used_input_tokens", 0),
            used_output_tokens=data.get("used_output_tokens", 0),
            used_cost_usd=Decimal(data.get("used_cost_usd", "0")),
            created_at=datetime.fromisoformat(data["created_at"]),
        )

    @classmethod
    def for_workflow(cls, execution_id: str, workflow_type: WorkflowType) -> SpendBudget:
        """Create a budget with defaults for the given workflow type."""
        defaults = DEFAULT_BUDGETS.get(workflow_type, DEFAULT_BUDGETS[WorkflowType.CUSTOM])
        return cls(
            execution_id=execution_id,
            workflow_type=workflow_type,
            max_input_tokens=int(defaults["max_input_tokens"]),
            max_output_tokens=int(defaults["max_output_tokens"]),
            max_cost_usd=Decimal(str(defaults["max_cost_usd"])),
        )
