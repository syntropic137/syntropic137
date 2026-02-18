# Claude API Security & Cost Protection

This document describes how AEF secures Claude API access and prevents runaway costs from compromised or misbehaving agents.

## The Risk

Claude API costs can escalate rapidly:

| Model | Input (1M tokens) | Output (1M tokens) |
|-------|-------------------|-------------------|
| Claude 3.5 Sonnet | $3.00 | $15.00 |
| Claude 3 Opus | $15.00 | $75.00 |

**At scale:**
- 100k agents × 10k tokens each = 1B tokens
- 1B tokens × $15/1M = **$15,000 per batch**

**If compromised:**
- Malicious agent loops indefinitely
- Generates maximum output tokens
- No spend limits = $100k+ monthly bill

## Security Architecture

### Token Never in Container

```
┌─────────────────────────────────────────────────────────────────────┐
│                          AEF Control Plane                           │
│                                                                     │
│   ┌─────────────────┐    ┌─────────────────┐                       │
│   │  Secret Store   │    │ Token Vending   │                       │
│   │                 │    │ Service         │                       │
│   │ ANTHROPIC_API_  │───▶│                 │                       │
│   │ KEY=sk-ant-... │    │ Issues scoped   │                       │
│   │                 │    │ tokens with     │                       │
│   │ NEVER LEAVES    │    │ spend limits    │                       │
│   │ THIS BOX        │    │                 │                       │
│   └─────────────────┘    └────────┬────────┘                       │
│                                   │                                 │
└───────────────────────────────────┼─────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────┐
│                            Agent Pod                                   │
│                                                                       │
│   ┌─────────────────────┐         ┌─────────────────────────────┐   │
│   │   Agent Container   │         │        Sidecar (Envoy)       │   │
│   │                     │         │                             │   │
│   │   Environment:      │         │   • Has scoped token        │   │
│   │   ANTHROPIC_BASE_   │────────▶│   • Injects x-api-key       │   │
│   │   URL=localhost:8080│         │   • Enforces spend limits   │   │
│   │                     │         │   • Logs all requests       │   │
│   │   NO API KEY!       │         │                             │   │
│   └─────────────────────┘         └──────────────┬──────────────┘   │
│                                                   │                  │
└───────────────────────────────────────────────────┼──────────────────┘
                                                    │
                                                    ▼
                                          ┌─────────────────┐
                                          │api.anthropic.com│
                                          └─────────────────┘
```

### Spend Limits

Each execution has a pre-allocated budget:

```python
@dataclass
class SpendBudget:
    """Budget allocated for an execution."""

    execution_id: str
    workflow_type: str

    # Token limits
    max_input_tokens: int
    max_output_tokens: int

    # Cost limits
    max_cost_usd: Decimal

    # Tracking
    used_input_tokens: int = 0
    used_output_tokens: int = 0
    used_cost_usd: Decimal = Decimal("0")

    @property
    def remaining_input_tokens(self) -> int:
        return self.max_input_tokens - self.used_input_tokens

    @property
    def remaining_cost_usd(self) -> Decimal:
        return self.max_cost_usd - self.used_cost_usd
```

### Budget Allocation by Workflow Type

| Workflow Type | Input Tokens | Output Tokens | Max Cost |
|--------------|--------------|---------------|----------|
| Research | 100,000 | 50,000 | $10.00 |
| Implementation | 500,000 | 200,000 | $50.00 |
| Review | 50,000 | 20,000 | $5.00 |
| Quick Fix | 10,000 | 5,000 | $1.00 |
| Custom | Configurable | Configurable | Configurable |

### Enforcement Points

```
Request Flow:

  Agent           Sidecar          Spend           Anthropic
    │                │            Tracker              │
    │                │               │                 │
    │ POST /messages │               │                 │
    │───────────────▶│               │                 │
    │                │               │                 │
    │                │ Check budget  │                 │
    │                │──────────────▶│                 │
    │                │               │                 │
    │                │               │──┐              │
    │                │               │  │ Compare:     │
    │                │               │  │ requested vs │
    │                │               │  │ remaining    │
    │                │               │◀─┘              │
    │                │               │                 │
    │                │◀──────────────│ OK / REJECT    │
    │                │               │                 │
    │          ┌─────┴─────┐        │                 │
    │          │ If REJECT │        │                 │
    │◀─────────│ Return 429│        │                 │
    │          │ with error│        │                 │
    │          └───────────┘        │                 │
    │                │               │                 │
    │          ┌─────┴─────┐        │                 │
    │          │ If OK:    │        │                 │
    │          │ Forward   │───────────────────────▶│
    │          │ request   │        │                 │
    │          └───────────┘        │                 │
    │                │               │                 │
    │                │◀──────────────────────────────│
    │                │               │                 │
    │                │ Record usage  │                 │
    │                │──────────────▶│                 │
    │                │               │                 │
    │◀───────────────│               │                 │
    │                │               │                 │
```

## Cost Estimation

Before each request, estimate tokens:

```python
def estimate_request_tokens(messages: list[dict]) -> int:
    """Estimate input tokens for a request.

    Uses tiktoken for accurate counting.
    Adds buffer for system overhead.
    """
    import tiktoken

    encoding = tiktoken.encoding_for_model("claude-3-sonnet")

    total = 0
    for msg in messages:
        # Count content tokens
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(encoding.encode(content))
        elif isinstance(content, list):
            for block in content:
                if block.get("type") == "text":
                    total += len(encoding.encode(block.get("text", "")))

    # Add overhead for message structure
    total += len(messages) * 10

    return total


def estimate_cost(
    input_tokens: int,
    max_output_tokens: int,
    model: str = "claude-3-5-sonnet-20241022",
) -> Decimal:
    """Estimate maximum cost for a request."""

    pricing = {
        "claude-3-5-sonnet-20241022": {
            "input": Decimal("3.00") / 1_000_000,
            "output": Decimal("15.00") / 1_000_000,
        },
        "claude-3-opus-20240229": {
            "input": Decimal("15.00") / 1_000_000,
            "output": Decimal("75.00") / 1_000_000,
        },
    }

    rates = pricing.get(model, pricing["claude-3-5-sonnet-20241022"])

    input_cost = Decimal(input_tokens) * rates["input"]
    output_cost = Decimal(max_output_tokens) * rates["output"]

    return input_cost + output_cost
```

## Alerting

Real-time alerts for anomalous spending:

```python
class SpendAlerter:
    """Monitors spend patterns and alerts on anomalies."""

    async def check_execution(
        self,
        execution_id: str,
        budget: SpendBudget,
    ) -> None:
        """Check execution spend and alert if needed."""

        # Alert at 80% budget usage
        if budget.used_cost_usd >= budget.max_cost_usd * Decimal("0.8"):
            await self.send_alert(
                level="warning",
                message=f"Execution {execution_id} at 80% budget",
                details={
                    "used": str(budget.used_cost_usd),
                    "max": str(budget.max_cost_usd),
                    "workflow": budget.workflow_type,
                },
            )

        # Alert on rapid spending (>$1/minute)
        spend_rate = await self.calculate_spend_rate(execution_id)
        if spend_rate > Decimal("1.00"):
            await self.send_alert(
                level="critical",
                message=f"Execution {execution_id} spending ${spend_rate}/min",
                details={
                    "rate": str(spend_rate),
                    "action": "Consider killing execution",
                },
            )

    async def check_global(self) -> None:
        """Check global spend patterns."""

        hourly_spend = await self.get_hourly_spend()

        # Alert if hourly spend exceeds threshold
        if hourly_spend > Decimal("100.00"):
            await self.send_alert(
                level="critical",
                message=f"Hourly spend at ${hourly_spend}",
                details={
                    "threshold": "$100.00",
                    "action": "Review active executions",
                },
            )
```

## Kill Switch

Emergency stop for runaway agents:

```python
class AgentKillSwitch:
    """Emergency controls for stopping agent spend."""

    async def kill_execution(self, execution_id: str) -> None:
        """Immediately stop an execution.

        1. Revoke all tokens for execution
        2. Kill agent container
        3. Mark execution as killed
        4. Log incident
        """
        # Revoke tokens (prevents further API calls)
        await self.token_vending.revoke_tokens(execution_id)

        # Kill container
        await self.workspace_router.destroy(execution_id)

        # Update status
        await self.execution_repo.mark_killed(
            execution_id,
            reason="Emergency kill switch activated",
        )

        # Log for audit
        logger.critical(
            "Execution killed via kill switch",
            execution_id=execution_id,
        )

    async def pause_all_executions(self) -> int:
        """Pause all active executions.

        Used when:
        - Suspected compromise
        - Unexpected spend spike
        - System maintenance

        Returns number of executions paused.
        """
        active = await self.execution_repo.get_active()

        for execution in active:
            await self.token_vending.revoke_tokens(execution.id)

        logger.critical(
            "All executions paused",
            count=len(active),
        )

        return len(active)
```

## Audit Trail

Every API call is logged:

```json
{
  "timestamp": "2025-12-12T01:30:00.123Z",
  "execution_id": "exec-abc123",
  "workflow_id": "research-v1",
  "session_id": "session-xyz",
  "request": {
    "model": "claude-3-5-sonnet-20241022",
    "messages_count": 5,
    "max_tokens": 4096,
    "estimated_input_tokens": 1500
  },
  "response": {
    "input_tokens": 1487,
    "output_tokens": 892,
    "stop_reason": "end_turn"
  },
  "cost": {
    "input_usd": "0.00446",
    "output_usd": "0.01338",
    "total_usd": "0.01784"
  },
  "budget": {
    "used_before": "0.50",
    "used_after": "0.52",
    "remaining": "9.48"
  },
  "latency_ms": 1234
}
```

## Configuration

### Environment Variables

```bash
# Anthropic API key (control plane only)
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx

# Spend limits (optional overrides)
SYN_CLAUDE_MAX_COST_PER_EXECUTION=50.00
SYN_CLAUDE_MAX_COST_PER_HOUR=500.00
SYN_CLAUDE_MAX_TOKENS_PER_REQUEST=100000

# Alerting
SYN_SPEND_ALERT_WEBHOOK=https://hooks.slack.com/services/xxx
SYN_SPEND_ALERT_EMAIL=ops@example.com
```

### Budget Configuration per Workflow

```yaml
# workflows/examples/research.yaml
id: research-workflow-v1
name: Research Workflow
type: research

# Budget configuration
budget:
  max_input_tokens: 100000
  max_output_tokens: 50000
  max_cost_usd: 10.00

  # Optional: per-phase limits
  phases:
    research:
      max_input_tokens: 50000
      max_output_tokens: 25000
    synthesis:
      max_input_tokens: 50000
      max_output_tokens: 25000
```

## Incident Response

### Suspected Token Leak

1. **Immediate**: Rotate API key in Anthropic console
2. **Investigate**: Check audit logs for unauthorized usage
3. **Revoke**: Call `pause_all_executions()` if needed
4. **Update**: Deploy new key to control plane
5. **Resume**: Restart executions with new tokens

### Runaway Spend

1. **Alert**: Automatic at 80% budget
2. **Investigate**: Check execution logs
3. **Kill**: Use kill switch if malicious
4. **Analyze**: Review agent behavior
5. **Prevent**: Adjust budget limits

### Prompt Injection Attempt

1. **Detect**: Unusual API patterns in logs
2. **Kill**: Immediately terminate execution
3. **Isolate**: Check if any tokens were exposed
4. **Analyze**: Review conversation history
5. **Prevent**: Update input validation

## Related Documentation

- [ADR-022: Secure Token Architecture](../adrs/ADR-022-secure-token-architecture.md)
- [GitHub App Security](./github-app-security.md)
- [Environment Configuration](../env-configuration.md)
