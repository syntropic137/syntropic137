---
title: "ADR-028: OpenTelemetry Integration for Agent Observability"
status: superseded
created: 2025-12-17
updated: 2025-12-19
superseded_by: ADR-029
author: Neural
---

# ADR-028: OpenTelemetry Integration for Agent Observability

## Status

**⚠️ SUPERSEDED by ADR-029 (Simplified Event System)**

- Created: 2025-12-17
- Superseded: 2025-12-19
- Author(s): Neural

> **⚠️ Superseded**: This ADR proposed using OpenTelemetry as the primary
> observability mechanism. ADR-029 simplified this by:
> 1. Using JSONL (`agentic_events`) instead of OTel for Syn137's custom dashboard
> 2. Storing events directly in TimescaleDB (no OTel Collector required)
> 3. OTel remains available for external monitoring if needed, but is not
>    required for Syn137's core observability pipeline.
>
> The `syn-adapters/observability/otel_config.py` and `conventions.py` files
> referenced here have been deleted.
> See `lib/agentic-primitives/docs/adrs/029-simplified-event-system.md`.

## Context

Syn137 executes agents inside isolated Docker containers. Previously, observability was handled by:

1. **JSONL files** written inside containers
2. **Collector service** that parsed and stored events
3. **TimescaleDB** for persistence and querying

This approach had gaps:

1. **Correlation**: Hard to correlate agent telemetry with platform events
2. **Granularity**: Only captured what we explicitly instrumented
3. **Standards**: Required custom tooling for dashboards

The Claude Code CLI now has **native OpenTelemetry support**:
- Emits metrics (token usage, costs)
- Emits traces (tool executions)
- Configurable via environment variables

### Hierarchy of Correlation

Syn137 has a clear hierarchy that must be preserved in telemetry:

```
Workflow Template (reusable definition)
    └── Workflow Execution (single run of template)
        └── Workflow Phase (isolated container)
            └── Agent Session (Claude CLI session)
```

Each level needs correlation IDs in OTel resource attributes.

## Decision

We will integrate OpenTelemetry as the **primary observability mechanism** for agent execution:

### 1. Semantic Conventions

Define `Syn137SemanticConventions` for platform-level attributes:

```python
class Syn137SemanticConventions:
    WORKFLOW_TEMPLATE_ID = "syn.workflow.template.id"
    WORKFLOW_EXECUTION_ID = "syn.workflow.execution.id"
    WORKFLOW_PHASE_ID = "syn.workflow.phase.id"
    WORKFLOW_PHASE_NAME = "syn.workflow.phase.name"
    AGENT_SESSION_ID = "syn.agent.session.id"
    GITHUB_PR_NUMBER = "syn.github.pr.number"
    GITHUB_REPO = "syn.github.repo"
```

### 2. OTel Config Factory

Create `create_phase_otel_config()` factory in `syn-adapters`:

```python
def create_phase_otel_config(
    workflow_id: str,
    execution_id: str,
    phase_id: str,
    phase_name: str,
    github_pr: str | None = None,
) -> OTelConfig:
    """Create OTel config with Syn137 resource attributes."""
```

### 3. Environment Injection

`WorkflowExecutor` injects OTel environment variables into containers:

```python
def _create_otel_environment(self, ...) -> dict[str, str]:
    return {
        "OTEL_EXPORTER_OTLP_ENDPOINT": get_collector_endpoint(),
        "OTEL_SERVICE_NAME": "agentic-agent",
        "OTEL_RESOURCE_ATTRIBUTES": ",".join([
            f"syn.workflow.execution.id={execution_id}",
            f"syn.workflow.phase.id={phase_id}",
            ...
        ]),
    }
```

### 4. OTel Collector in Docker Compose

Add `otel-collector` service to development stack:

```yaml
otel-collector:
  image: otel/opentelemetry-collector-contrib:0.92.0
  ports:
    - "4317:4317"  # OTLP gRPC
    - "4318:4318"  # OTLP HTTP
```

### 5. UI Correlation

Add `agent_session_id` to `PhaseExecutionDetail` for UI display and OTel correlation.

## Alternatives Considered

### Alternative 1: Keep JSONL + Collector

**Description**: Continue with custom collector parsing JSONL from containers

**Pros**:
- No new infrastructure
- Works today

**Cons**:
- No correlation with external systems
- Custom dashboards required
- Duplicates what OTel already provides

**Reason for rejection**: Fighting the platform; Claude CLI already emits OTel.

### Alternative 2: Hybrid (OTel + Legacy)

**Description**: Emit both OTel and JSONL during transition

**Pros**:
- Gradual migration
- Fallback if OTel fails

**Cons**:
- Double complexity
- Confusion about source of truth

**Reason for rejection**: Alpha stage; clean break acceptable.

## Consequences

### Positive Consequences

- **Standard observability**: Use Jaeger, Prometheus, Grafana
- **Correlation**: All telemetry linked via trace context
- **Granular metrics**: Token usage per tool, per phase, per execution
- **Ecosystem**: Alert on anomalies using standard tooling

### Negative Consequences

- **Infrastructure requirement**: Must deploy OTel Collector
- **Learning curve**: Teams must understand OTel concepts
- **Breaking change**: Legacy JSONL pipelines deprecated

### Neutral Consequences

- TimescaleDB remains for long-term storage (OTel Collector exports to it)
- Dashboard queries unchanged (data still in same tables)

## Implementation Notes

### Files Created

```
packages/syn-adapters/src/syn_adapters/observability/
├── __init__.py
├── conventions.py      # Syn137SemanticConventions
└── otel_config.py      # create_phase_otel_config, get_collector_endpoint

docker/
├── docker-compose.dev.yaml  # Added otel-collector service
└── otel-collector-config.yaml  # Collector configuration
```

### Files Modified

```
packages/syn-adapters/src/syn_adapters/orchestration/workflow_executor.py
  - Added _create_otel_environment() method
  - Inject OTel env vars into workspace creation

packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py
  - Added extra_environment parameter to create_workspace()

packages/syn-domain/src/syn_domain/.../workflow_execution_detail.py
  - Added agent_session_id field

apps/syn-dashboard-ui/src/types/index.ts
  - Added agent_session_id to PhaseExecutionDetail

apps/syn-dashboard-ui/src/pages/ExecutionDetail.tsx
  - Display agent_session_id for OTel correlation
```

### Endpoint Resolution

`get_collector_endpoint()` resolves in order:
1. `OTEL_EXPORTER_OTLP_ENDPOINT` (explicit override)
2. `SYN_OTEL_COLLECTOR_HOST` + `SYN_OTEL_COLLECTOR_PORT` (Docker network)
3. Default: `http://localhost:4317`

### OTel Collector Configuration

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

exporters:
  logging:
    verbosity: detailed
  prometheus:
    endpoint: "0.0.0.0:8889"

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [logging]
    metrics:
      receivers: [otlp]
      exporters: [logging, prometheus]
```

## References

- [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)
- [Claude CLI OTel Support](https://code.claude.com/docs/en/headless)
- ADR-015: Agent Observability
- ADR-026: TimescaleDB Observability Storage
- ADR-027: Unified Workflow Executor
- agentic-primitives ADR-026: OTel-First Observability Architecture
