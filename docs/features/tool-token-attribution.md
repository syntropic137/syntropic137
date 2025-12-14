# Tool Token Attribution

This document describes the tool token attribution feature, which provides granular insight into how tokens are consumed by different tools during Claude sessions.

## Overview

When Claude uses tools (like Read, Write, Shell), tokens are consumed for:
1. **Tool Use**: The tokens in the `tool_use` block (Claude's tool call)
2. **Tool Result**: The tokens in the `tool_result` block (your response to Claude)

This feature estimates and tracks these tokens per-tool, enabling you to understand:
- Which tools consume the most tokens
- How much of your cost is attributable to each tool
- Whether file operations (Read/Write) dominate your token usage

## How It Works

### Token Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     Claude API Response                         │
│                                                                 │
│  { "role": "assistant", "content": [                           │
│      { "type": "text", "text": "I'll read that file..." },     │
│      { "type": "tool_use",                                     │
│        "name": "Read",                                         │
│        "input": { "file_path": "/path/to/file.py" }            │
│      }                                                          │
│  ]}                                                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ToolTokenEstimator estimates tokens:
              - Read tool_use: ~30 tokens (tool name + JSON input)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Your Tool Response                          │
│                                                                 │
│  { "role": "user", "content": [                                │
│      { "type": "tool_result",                                  │
│        "content": "def hello():\n    print('world')\n..."      │
│      }                                                          │
│  ]}                                                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ToolTokenEstimator estimates tokens:
              - Read tool_result: ~500 tokens (file content)
```

### Token Estimation Heuristics

Since exact token counts require API calls, we use estimation:

| Content Type | Characters per Token | Example |
|--------------|---------------------|---------|
| JSON/Code | 3.0-4.0 | `{"file_path": "/a/b.py"}` |
| Plain text | 4.0-4.5 | "Hello, World!" |
| Tool overhead | ~15 tokens | Structural tokens for tool_use |

Accuracy is typically within 10-15% of actual token counts.

## API

### Session Cost with Tool Breakdown

```http
GET /api/costs/sessions/{session_id}
```

Response includes:

```json
{
  "session_id": "session_123",
  "total_cost_usd": "0.52",
  "total_tokens": 15000,
  
  "tokens_by_tool": {
    "Write": 8000,
    "Read": 5000,
    "Shell": 1500,
    "Grep": 500
  },
  
  "cost_by_tool_tokens": {
    "Write": "0.28",
    "Read": "0.16",
    "Shell": "0.05",
    "Grep": "0.02"
  }
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `tokens_by_tool` | `dict[str, int]` | Total tokens (tool_use + tool_result) per tool |
| `cost_by_tool_tokens` | `dict[str, str]` | Estimated cost in USD per tool |

## UI Components

### ToolCostBreakdown

A React component that displays a bar chart of token usage by tool:

```tsx
import { ToolCostBreakdown } from '@/components'

<ToolCostBreakdown
  tokensByTool={sessionCost.tokens_by_tool}
  costByToolTokens={sessionCost.cost_by_tool_tokens}
  maxTools={5}  // Show top 5 tools
/>
```

### SessionCostCard with Tool Tokens

Enable tool token display in the SessionCostCard:

```tsx
<SessionCostCard
  cost={sessionCost}
  showBreakdown={true}
  showToolTokens={true}  // Enable tool token breakdown
/>
```

## Interpreting the Data

### Common Patterns

1. **Read-Heavy Sessions**: Sessions that read many files will have high `Read` tokens (mostly in tool_result)
2. **Write-Heavy Sessions**: Code generation sessions have high `Write` tokens (in tool_use, as the file content is in the request)
3. **Shell-Heavy Sessions**: Build/test sessions may have high `Shell` tokens

### Cost Attribution

Tool tokens are attributed to costs using the model's input/output pricing:
- `tool_use` tokens → Output tokens (more expensive)
- `tool_result` tokens → Input tokens (cheaper, may use cache)

### Example: File Read

```
Read("/path/to/large_file.py")
  - tool_use: 30 tokens (output @ $15/M)  = $0.00045
  - tool_result: 5000 tokens (input @ $3/M) = $0.015
  Total: $0.01545
```

### Example: File Write

```
Write("/path/to/new_file.py", content="..1000 chars..")
  - tool_use: 300 tokens (output @ $15/M)  = $0.0045
  - tool_result: 10 tokens (input @ $3/M) = $0.00003
  Total: $0.00453
```

## Limitations

1. **Estimates Only**: Token counts are heuristic-based, not from the API
2. **Aggregate View**: Shows totals per tool, not individual calls
3. **Cache Attribution**: Cache tokens are counted in total but not broken down by tool
4. **Tool Definition Overhead**: Tokens for tool schemas in system prompt are not attributed

## Technical Details

### Implementation

- **ToolTokenEstimator**: `packages/aef-domain/.../costs/services/tool_token_estimator.py`
- **ToolTokens Value Object**: `packages/aef-domain/.../costs/_shared/tool_tokens.py`
- **CostRecordedEvent**: Extended with `tool_token_breakdown` field
- **SessionCostProjection**: Aggregates tool tokens across events

### Event Schema

The `CostRecordedEvent` includes:

```python
tool_token_breakdown: dict[str, dict[str, int]] = field(default_factory=dict)
# Example: {"Read": {"tool_use": 30, "tool_result": 5000}}
```

### Architecture

See [ADR-018: Commands vs Observations](../adrs/ADR-018-commands-vs-observations-event-architecture.md) for the underlying event architecture.
