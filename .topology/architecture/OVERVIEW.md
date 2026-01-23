# System Overview

> **Generated**: 2026-01-23  
> **VSA Version**: 0.6.1-beta  
> **Schema Version**: 1.1.0

---

This document provides a high-level overview of the system architecture, including bounded contexts, aggregates, and their relationships.

## Statistics

- **Bounded Contexts**: 9
- **Total Features/Slices**: 80
- **Aggregates**: 6
- **Commands**: 12
- **Events**: 31

## System Context

High-level view of the system showing bounded contexts and external actors.

```mermaid
C4Context
  title System Context Diagram

  Person(user, "User", "Interacts with the system")
  System(system, "VSA System", "Event-sourced system built with VSA")

  Rel(user, system, "Uses")

```

## Bounded Contexts

The system is organized into multiple bounded contexts, each with its own domain model.

```mermaid
C4Container
  title Container Diagram - Bounded Contexts

  Person(user, "User")
  System_Boundary(system, "VSA System") {
    Container(metrics, "metrics", "Bounded Context", "5 feature(s)")
    Container(artifacts, "artifacts", "Bounded Context", "11 feature(s)")
    Container(costs, "costs", "Bounded Context", "9 feature(s)")
    Container(workflows, "workflows", "Bounded Context", "15 feature(s)")
    Container(agents, "agents", "Bounded Context", "0 feature(s)")
    Container(observability, "observability", "Bounded Context", "7 feature(s)")
    Container(workspaces, "workspaces", "Bounded Context", "12 feature(s)")
    Container(sessions, "sessions", "Bounded Context", "10 feature(s)")
    Container(github, "github", "Bounded Context", "11 feature(s)")
  }

  Rel(user, metrics, "Uses")

```

## Context Details

Detailed breakdown of each bounded context and its features/slices.

### metrics

Path: `./packages/aef-domain/src/aef_domain/contexts/metrics`

**Features/Slices:**

- `get_metrics` (5 files)
- `queries` (2 files)
- `read_models` (2 files)

### artifacts

Path: `./packages/aef-domain/src/aef_domain/contexts/artifacts`

**Features/Slices:**

- `list_artifacts` (4 files)
- `create_artifact` (3 files)
- `upload_artifact` (3 files)
- `queries` (2 files)
- `commands` (3 files)
- `read_models` (2 files)
- `services` (3 files)

### costs

Path: `./packages/aef-domain/src/aef_domain/contexts/costs`

**Infrastructure:**

- `services`

**Features/Slices:**

- `execution_cost` (5 files)
- `record_cost` (2 files)
- `session_cost` (5 files)
- `queries` (3 files)
- `read_models` (3 files)

### workflows

Path: `./packages/aef-domain/src/aef_domain/contexts/workflows`

**Features/Slices:**

- `get_execution_detail` (2 files)
- `execute_workflow` (4 files)
- `get_workflow_detail` (5 files)
- `list_executions` (3 files)
- `create_workflow` (3 files)
- `list_workflows` (5 files)
- `cleanup` (2 files)
- `queries` (3 files)
- `commands` (3 files)
- `read_models` (5 files)

_... and 1 more features_

### agents

Path: `./packages/aef-domain/src/aef_domain/contexts/agents`

### observability

Path: `./packages/aef-domain/src/aef_domain/contexts/observability`

**Features/Slices:**

- `token_metrics` (5 files)
- `tool_timeline` (5 files)
- `queries` (3 files)
- `read_models` (3 files)

### workspaces

Path: `./packages/aef-domain/src/aef_domain/contexts/workspaces`

**Features/Slices:**

- `terminate_workspace` (1 files)
- `workspace_metrics` (4 files)
- `execute_command` (1 files)
- `create_workspace` (1 files)
- `destroy_workspace` (1 files)
- `inject_tokens` (1 files)
- `queries` (2 files)
- `commands` (5 files)
- `read_models` (2 files)

### sessions

Path: `./packages/aef-domain/src/aef_domain/contexts/sessions`

**Features/Slices:**

- `list_sessions` (5 files)
- `complete_session` (3 files)
- `start_session` (3 files)
- `record_operation` (4 files)
- `queries` (2 files)
- `commands` (4 files)
- `read_models` (2 files)

### github

Path: `./packages/aef-domain/src/aef_domain/contexts/github`

**Features/Slices:**

- `refresh_token` (3 files)
- `install_app` (2 files)
- `list_repos` (2 files)
- `get_installation` (4 files)
- `aggregates` (1 files)
- `queries` (3 files)
- `commands` (2 files)
- `read_models` (3 files)

