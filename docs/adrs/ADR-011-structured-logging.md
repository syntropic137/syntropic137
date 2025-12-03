---
title: "ADR-011: Structured Logging with agentic-logging"
status: accepted
created: 2025-12-03
author: AI Agent (Claude)
---

# ADR-011: Structured Logging with agentic-logging

## Status

**Accepted** (2025-12-03)

## Context

The Agentic Engineering Framework needs consistent, structured logging across all
components for:

1. **AI Agent Debugging** - Structured JSON logs are parseable by AI agents
2. **Developer Experience** - Human-readable logs during development
3. **Session Correlation** - Trace events across workflow execution
4. **Production Observability** - JSON output for log aggregation systems

## Decision

**We will use `agentic-logging` from the `agentic-primitives` submodule** as our
centralized logging solution.

This provides:
- Structured JSON output for AI-optimized logging
- Human-readable console format for development
- Per-component log level control via environment variables
- Session ID correlation across components
- Fail-safe operation (logging errors never crash the system)

### Usage

```python
from agentic_logging import get_logger, setup_logging

# Initialize logging (call once at application startup)
setup_logging()

# Get a logger for your component
logger = get_logger(__name__)

# Log with structured context
logger.info(
    "Workflow execution started",
    extra={
        "workflow_id": workflow.id,
        "phases": len(workflow.phases),
    }
)
```

### Configuration

Configure via environment variables:

```bash
# Global log level (default: INFO)
LOG_LEVEL=DEBUG

# Output format: json | human (default: human for TTY, json otherwise)
LOG_FORMAT=json

# Per-component log levels (override global)
LOG_LEVEL_AEF_DASHBOARD=DEBUG
LOG_LEVEL_AEF_ADAPTERS=INFO
LOG_LEVEL_EVENT_SUBSCRIPTION=DEBUG

# Session correlation (automatically set by agentic-primitives hooks)
AGENTIC_SESSION_ID=session-abc123
```

### Log Level Strategy

| Environment | Default Level | Format |
|------------|---------------|--------|
| Development | DEBUG | human |
| Testing | WARNING | json |
| Production | INFO | json |

### Output Formats

**Human Format** (development):
```
2025-12-03 10:30:45 | INFO | aef_dashboard.main | Workflow started | workflow_id=wf-123
```

**JSON Format** (production):
```json
{"timestamp": "2025-12-03T10:30:45Z", "level": "INFO", "logger": "aef_dashboard.main", "message": "Workflow started", "workflow_id": "wf-123"}
```

## Alternatives Considered

### 1. Custom Logging Implementation

Build our own logging system tailored to AEF.

**Rejected**: Duplicates effort already done in agentic-primitives. Using the
submodule keeps things consistent across the ecosystem.

### 2. Standard Python Logging Only

Use Python's built-in `logging` module without structured output.

**Rejected**: Lacks structured JSON output needed for AI agent debugging and
log aggregation systems.

### 3. structlog or loguru

Use a third-party logging library.

**Rejected**: Adds external dependencies. agentic-logging uses only
`python-json-logger` (2.0.7+) which is well-maintained and minimal.

## Consequences

### Positive

- Consistent logging format across all AEF components
- AI-friendly structured output for debugging
- Per-component log levels enable focused debugging
- Session correlation across workflow execution
- Familiar Python logging API

### Negative

- Submodule dependency on agentic-primitives
- Small learning curve for environment variable configuration
- Migration needed for existing `logging.getLogger()` calls

## Implementation

Components that have been updated to use `agentic_logging`:

- [x] `aef-dashboard/main.py` - Dashboard startup and lifespan
- [x] `aef-dashboard/services/execution.py` - Workflow execution service  
- [x] `aef-adapters/subscriptions/service.py` - Event subscription service
- [ ] Other components (as needed)

## References

- [agentic-primitives ADR-014](../../lib/agentic-primitives/docs/adrs/014-centralized-agentic-logging.md) - Original logging design
- [agentic_logging README](../../lib/agentic-primitives/lib/python/agentic_logging/README.md) - Detailed usage guide

