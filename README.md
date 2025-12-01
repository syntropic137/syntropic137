# Agentic Engineering Framework

Event-sourced system for tracking AI agent work across workflows, capturing metrics for observability and optimization.

## Overview

The Agentic Engineering Framework provides:

- **Composable Workflows**: Define reusable workflow phases with inputs and output artifacts
- **Event Sourcing**: All state changes captured as immutable events
- **Metrics & Observability**: Detailed token tracking and execution metrics
- **Vertical Slice Architecture (VSA)**: Clean bounded contexts for parallel development

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [just](https://just.systems/) (command runner)
- Docker (for development environment)

### Installation

```bash
# Clone with submodules
git clone --recursive https://github.com/AgentParadise/agentic-engineering-framework.git
cd agentic-engineering-framework

# Install dependencies
just install

# Initialize submodules (if not cloned with --recursive)
just submodules
```

### Development Environment

```bash
# Start Docker services (PostgreSQL)
just dev

# Run QA checks
just qa

# Run tests
just test
```

### CLI Usage

```bash
# List available workflows
aef list

# Run a workflow
aef run simple-research --topic "AI agents"

# Check workflow status
aef status <workflow-id>

# View artifacts
aef artifacts <workflow-id>

# View metrics
aef metrics <workflow-id>
```

## Project Structure

```
agentic-engineering-framework/
├── lib/                          # Git submodules
│   ├── agentic-primitives/       # Composable agent building blocks
│   └── event-sourcing-platform/  # Event sourcing infrastructure
│
├── apps/
│   └── cli/                      # `aef` CLI application
│
├── packages/
│   ├── domain/                   # Core domain + VSA contexts
│   ├── adapters/                 # External integrations
│   └── shared/                   # Logging, DI, utilities
│
├── workflows/                    # Workflow YAML definitions
├── docker/                       # Docker configurations
└── docs/                         # Documentation
```

## Architecture

### Bounded Contexts

- **Workflows**: Workflow definitions, phases, and execution lifecycle
- **Agents**: Agent sessions, token tracking, and execution metrics
- **Artifacts**: Artifact storage, metadata, and retrieval

### Key Patterns

| Pattern | Implementation |
|---------|---------------|
| Event Sourcing | Commands → Aggregates → Events |
| Event Processing | Processor/Todo pattern (no complex sagas) |
| Architecture | Vertical Slice Architecture (VSA) |
| Logging | Centralized DI logger, structured, detailed |

## Development Commands

```bash
just --list              # Show all commands

# Quality Assurance
just qa                  # Run full QA pipeline
just lint                # Run linter
just format              # Format code
just typecheck           # Run type checker
just test                # Run tests with coverage

# Development
just dev                 # Start Docker environment
just dev-down            # Stop Docker environment
just seed-workflows      # Seed workflows from YAML

# VSA
just vsa-validate        # Validate architecture
just vsa-scaffold ctx slice  # Create new vertical slice
```

## License

MIT

