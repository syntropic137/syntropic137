# ADR-039: Context Window and Cost Tracking

## Status
Accepted

## Context

AEF needs accurate token usage and cost tracking for agent sessions to:
1. Monitor context window utilization for optimization
2. Track costs accurately for billing and budgeting
3. Enable evals and benchmarking with reliable metrics
4. Alert when sessions approach context limits

### The Problem

Claude CLI emits token usage in multiple places:
- **Per-turn `usage` field** in `assistant` messages (real-time, partial)
- **Final `result` event** with authoritative `total_cost_usd` and `modelUsage`

We need to understand:
1. How to calculate context window from available data
2. What the authoritative source of truth is for costs
3. How compaction affects these calculations

## Decision

### Context Window Formula

Based on [Anthropic's documentation](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching), the context window for any turn is:

```
context_window = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
```

From the `usage` field in each `assistant` message event:
```json
{
  "usage": {
    "input_tokens": 3,
    "cache_creation_input_tokens": 4907,
    "cache_read_input_tokens": 13678,
    "output_tokens": 5
  }
}
```

**Context window** = 3 + 4,907 + 13,678 = **18,588 tokens**

### Metrics to Track

| Metric | Source | Formula/Field |
|--------|--------|---------------|
| Per-turn context window | `assistant.message.usage` | `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` |
| Max context reached | Derived | Max of above across all turns |
| Cumulative input tokens | `result.usage` | `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` |
| Cumulative output tokens | `result.usage` | `output_tokens` |
| Total cost (authoritative) | `result` | `total_cost_usd` |
| Per-model breakdown | `result` | `modelUsage` object |

### Authoritative Sources

1. **Cost**: Use `result.total_cost_usd` - this is the authoritative final cost from Claude
2. **Token totals**: Use `result.usage` - cumulative totals for the session
3. **Model breakdown**: Use `result.modelUsage` - shows Sonnet vs Haiku usage and costs

### Example `result` Event

```json
{
  "type": "result",
  "total_cost_usd": 0.09459784999999998,
  "usage": {
    "input_tokens": 33,
    "cache_creation_input_tokens": 7189,
    "cache_read_input_tokens": 111517,
    "output_tokens": 2168
  },
  "modelUsage": {
    "claude-sonnet-4-5-20250929": {
      "inputTokens": 33,
      "outputTokens": 2168,
      "cacheReadInputTokens": 111517,
      "cacheCreationInputTokens": 7189,
      "costUSD": 0.09303285,
      "contextWindow": 200000,
      "maxOutputTokens": 64000
    },
    "claude-haiku-4-5-20251001": {
      "inputTokens": 1315,
      "outputTokens": 50,
      "costUSD": 0.001565,
      "contextWindow": 200000,
      "maxOutputTokens": 64000
    }
  }
}
```

### Compaction Handling

**Decision**: Compaction is not a primary concern for AEF's phase-based execution model.

Reasons:
1. **Each phase starts fresh** - context doesn't accumulate across phases
2. **Subagents are isolated** - each has its own context window
3. **Auto-compaction threshold** - ~190K tokens, rarely reached in typical phases
4. **`/compact` is interactive** - can't be triggered in print mode (`-p`)

**Safety net**: The existing `PreCompact` hook will fire if compaction ever triggers, allowing us to:
- Alert when compaction happens
- Log before/after token counts
- Investigate why context grew large

### Reconciliation

To ensure tracking accuracy:
1. **Real-time estimates**: Calculate from per-turn `usage` fields
2. **Final reconciliation**: Compare estimates to `result` event values
3. **Alert on drift**: If estimates differ significantly from final values, log a warning

## Consequences

### Positive
- Clear, documented formula for context window calculation
- Authoritative source of truth for costs (`result.total_cost_usd`)
- Multi-model cost breakdown available (`modelUsage`)
- Compaction handled via existing hook infrastructure

### Negative
- Real-time estimates may differ slightly from final values (acceptable)
- Compaction recording not captured (not needed for phase-based model)

### Neutral
- Context window tracking requires summing three token fields
- Per-model costs require parsing `modelUsage` object

## References

- [Anthropic Token Counting Docs](https://docs.anthropic.com/en/docs/build-with-claude/token-counting)
- [Anthropic Context Windows Docs](https://docs.anthropic.com/en/docs/build-with-claude/context-windows)
- [Anthropic Prompt Caching Docs](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
- Recording: `v2.1.29_claude-sonnet-4-5_context-tracking.jsonl`
- Recording: `v2.1.29_claude-sonnet-4-5_multi-model-usage/`
