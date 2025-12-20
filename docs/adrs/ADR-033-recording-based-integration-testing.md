# ADR-033: Recording-Based Integration Testing

## Status

Accepted

## Context

We need to test the AEF event pipeline without spending API tokens. Manual testing finds bugs that automated tests miss, indicating gaps in test coverage.

**Challenges:**

1. Agent API calls are expensive ($0.01-0.10+ per test)
2. Integration tests need realistic event streams
3. Tests should be deterministic and reproducible
4. Need to test full pipeline: events → collector → projections

**Prior Art:**

- VCR.py and pytest-recording for HTTP request recording
- Playwright's trace recording for browser tests
- agentic-primitives already has `SessionRecorder`/`SessionPlayer`

## Decision

Use recorded agent sessions from `agentic-primitives` with a new `RecordingEventStreamAdapter` that implements `EventStreamPort`.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AEF Event Flow                               │
│                                                                     │
│  EventStreamPort (interface)                                        │
│       │                                                             │
│       ├── DockerEventStreamAdapter (production)                     │
│       │       └── streams from docker exec                          │
│       │                                                             │
│       ├── MemoryEventStreamAdapter (unit tests)                     │
│       │       └── yields pre-configured lines                       │
│       │                                                             │
│       └── RecordingEventStreamAdapter (integration tests)           │
│               └── yields lines from SessionPlayer recordings        │
│                                                                     │
│           ↓                                                         │
│    WorkspaceService.stream()                                        │
│           ↓                                                         │
│    Collector / Projections / Assertions                             │
└─────────────────────────────────────────────────────────────────────┘
```

### Components

1. **SessionRecorder** (agentic-primitives): Captures agent events with timing to JSONL
2. **SessionPlayer** (agentic-primitives): Replays recordings at configurable speed
3. **RecordingEventStreamAdapter** (aef-adapters): Bridges recordings to AEF's event pipeline

### Usage

```python
from aef_adapters.workspace_backends.recording import RecordingEventStreamAdapter
from aef_adapters.workspace_backends.service import WorkspaceService

# Load recording by task name
adapter = RecordingEventStreamAdapter("simple-bash")

# Use with WorkspaceService
service = WorkspaceService.create_test(event_stream=adapter)

async with service.create_workspace(execution_id="test") as ws:
    async for line in ws.stream(["claude", "-p", "test"]):
        # Events replay from recording - no API calls!
        process_event(line)
```

### Configuration

Set `AGENTIC_RECORDINGS_DIR` environment variable to point to recordings directory:

```bash
export AGENTIC_RECORDINGS_DIR=/path/to/recordings
```

In pytest, this is configured automatically in `conftest.py`.

## Consequences

### Positive

- ✅ **Zero-cost integration testing** - no API calls needed
- ✅ **Deterministic tests** - same recording = same results
- ✅ **Fast execution** - ~1000x real-time replay possible
- ✅ **Full pipeline testing** - events flow through real collectors/projections
- ✅ **Easy to add scenarios** - just capture new recordings

### Negative

- ⚠️ **Recordings become stale** - must re-record after schema changes
- ⚠️ **Can't test live API behavior** - use E2E tests for that
- ⚠️ **Recordings are snapshots** - may not cover edge cases

### Mitigations

1. **Schema versioning**: Recordings include `event_schema_version` for migration
2. **Documentation**: Clear guidance on when to re-record
3. **Layered testing**: E2E tests supplement recording-based tests

## Implementation

### Files Created

```
packages/aef-adapters/src/aef_adapters/workspace_backends/recording/
├── __init__.py
└── adapter.py                    # RecordingEventStreamAdapter

packages/aef-adapters/tests/workspace_backends/recording/
├── __init__.py
├── test_adapter.py               # Unit tests
└── test_integration.py           # Integration tests with real recordings
```

### Recordings Location

```
lib/agentic-primitives/providers/workspaces/claude-cli/fixtures/recordings/
├── v2.0.74_claude-sonnet-4-5_simple-bash.jsonl
├── v2.0.74_claude-sonnet-4-5_file-create.jsonl
├── v2.0.74_claude-sonnet-4-5_multi-tool.jsonl
└── ... (7 recordings total)
```

## References

- [ADR-029: AI Agent Testing & Verification](ADR-029-ai-agent-testing-verification.md)
- [ADR-030: Session Recording for Testing](../../lib/agentic-primitives/docs/adrs/030-session-recording-testing.md) (agentic-primitives)
- [ADR-013: Integration Testing Strategy](ADR-013-integration-testing-strategy.md)
