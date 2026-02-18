# syn-tokens

Token vending and spend tracking for secure agent execution at scale.

## Overview

This package implements the **zero-trust token architecture** where agent containers never hold raw API keys. All secrets flow through token vending services with:

- ⏱️ **Short TTL**: Tokens expire in 5 minutes
- 🎯 **Scoped permissions**: Per-execution, per-repo access
- 💰 **Cost limits**: Spend caps per execution
- 📝 **Full audit trail**: Every token tracked

## Installation

```bash
uv pip install -e packages/syn-tokens/
```

## Components

### TokenVendingService

Issues short-lived, scoped tokens for agent operations.

```python
from syn_tokens import TokenVendingService, TokenScope, TokenType

# Create service with in-memory store (use Redis for production)
service = TokenVendingService(InMemoryTokenStore())

# Issue a token for an execution
token = await service.vend_token(
    execution_id="exec-123",
    token_type=TokenType.ANTHROPIC,
    scope=TokenScope(
        allowed_apis=["anthropic:messages"],
        max_cost_usd=Decimal("10.00"),
    ),
)

# Token auto-expires in 5 minutes
print(f"Token: {token.token_id}, expires in {token.seconds_until_expiry}s")

# Revoke all tokens when execution completes
await service.revoke_tokens("exec-123")
```

### SpendTracker

Tracks and limits Claude API spend per execution.

```python
from syn_tokens import SpendTracker, WorkflowType

tracker = SpendTracker(InMemoryBudgetStore())

# Allocate budget for execution (based on workflow type)
budget = await tracker.allocate_budget(
    execution_id="exec-123",
    workflow_type=WorkflowType.RESEARCH,  # 100k input, 50k output, $10 max
)

# Check budget before API call
result = await tracker.check_budget("exec-123", input_tokens=5000, output_tokens=2000)
if not result.allowed:
    raise BudgetExceededError(result.reason)

# Record actual usage after API call
await tracker.record_usage("exec-123", input_tokens=5000, output_tokens=1800)

# Get usage summary
summary = await tracker.get_usage_summary("exec-123")
print(f"Cost: ${summary['cost_usd']['used']} / ${summary['cost_usd']['max']}")
```

### Default Budgets by Workflow Type

| Workflow | Input Tokens | Output Tokens | Max Cost |
|----------|-------------|---------------|----------|
| Research | 100,000 | 50,000 | $10.00 |
| Implementation | 500,000 | 200,000 | $50.00 |
| Review | 50,000 | 20,000 | $5.00 |
| Quick Fix | 10,000 | 5,000 | $1.00 |

### Alert Thresholds

- **Warning**: 80% budget usage
- **Critical**: 95% budget usage

Alerts are sent via configurable callback:

```python
async def alert_handler(alert: SpendAlert):
    await send_slack_notification(f"⚠️ {alert.message}")

tracker = SpendTracker(store, alert_callback=alert_handler)
```

## Storage Backends

### In-Memory (Testing/Development)

```python
from syn_tokens.vending import InMemoryTokenStore
from syn_tokens.spend import InMemoryBudgetStore

token_store = InMemoryTokenStore()
budget_store = InMemoryBudgetStore()
```

### Redis (Production)

```python
from redis.asyncio import Redis
from syn_tokens.vending import RedisTokenStore, configure_redis
from syn_tokens.spend import RedisBudgetStore, configure_redis_spend_tracker

redis = Redis.from_url("redis://localhost:6379")

# Tokens auto-expire via Redis TTL
await configure_redis(redis)
await configure_redis_spend_tracker(redis)
```

## Security Model

| Threat | Mitigation | Blast Radius |
|--------|------------|--------------|
| Token in container | Token NOT in container | None |
| Prompt injection | No token to steal | None |
| Compromised container | 5-min TTL | 5 min window |
| Runaway spend | Per-execution caps | $10-50 max |

## Related Documentation

- [ADR-022: Secure Token Architecture](../../docs/adrs/ADR-022-secure-token-architecture.md)
- [Claude API Security](../../docs/deployment/claude-api-security.md)
- [GitHub App Security](../../docs/deployment/github-app-security.md)
- [Sidecar Proxy](../../docker/sidecar-proxy/README.md)

## Future Work

> **Phase 6: Observability** - Not yet implemented

- [ ] **Token Usage Dashboard** - Grafana dashboard showing token issuance/revocation rates, TTL distributions
- [ ] **Spend Tracking Dashboard** - Real-time cost monitoring per execution, per workflow type
- [ ] **Anomaly Detection Alerts** - ML-based detection of unusual spend patterns, burst requests
- [ ] **Security Incident Runbook** - Documented procedures for token leaks, spend anomalies, emergency revocation

### Contributions Welcome

If you'd like to implement any of the above, please open an issue first to discuss the approach.

## Testing

```bash
# Run all tests
uv run pytest packages/syn-tokens/tests/ -v

# 44 tests covering:
# - Token lifecycle (vend, validate, revoke)
# - Scope restrictions
# - Budget allocation and tracking
# - Alert thresholds
# - Serialization roundtrips
```

## License

MIT
