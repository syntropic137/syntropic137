# ADR-002: uv Monorepo Architecture

## Status
Accepted

## Date
2025-12-01

## Context

We need a clean, scalable Python monorepo structure for the Agentic Engineering Framework. After researching uv's workspace capabilities, we've identified the canonical patterns for Python monorepos.

### Key Constraints
1. Python's import system requires directory names to match import names
2. Build tools need clear separation between project metadata and source code
3. We want to avoid import pollution and maintain clean namespaces
4. Dependencies should be consistent across all workspace members

## Decision

### 1. Build Backend: `uv_build`

We use `uv_build` as the build backend instead of `hatchling`:

```toml
[build-system]
requires = ["uv_build>=0.6.0"]
build-backend = "uv_build"
```

**Rationale:**
- Rust-powered, extremely fast
- Zero-config for pure Python packages
- PEP 517 compliant
- Native uv integration

### 2. Naming Convention (Critical)

| Thing | Convention | Example |
|-------|------------|---------|
| Project name (pyproject.toml) | **hyphens** | `aef-domain` |
| Import namespace (src/ folder) | **snake_case** | `aef_domain` |
| Installation | same as project | `uv add aef-domain` |
| Import in code | same as namespace | `import aef_domain` |

This mapping is canonical and avoids "hyphen in import path" errors.

### 3. Directory Structure

```
agentic-engineering-framework/
├── pyproject.toml              # Workspace root
├── uv.lock                     # Single lockfile for all members
├── justfile                    # Task runner
│
├── lib/                        # Git submodules (external deps)
│   ├── agentic-primitives/
│   └── event-sourcing-platform/
│
├── apps/                       # Deployable applications
│   └── aef-cli/
│       ├── pyproject.toml
│       └── src/
│           └── aef_cli/
│               ├── __init__.py
│               ├── main.py
│               └── commands/
│
├── packages/                   # Reusable libraries
│   ├── aef-domain/
│   │   ├── pyproject.toml
│   │   └── src/
│   │       └── aef_domain/
│   │           ├── __init__.py
│   │           └── contexts/
│   │
│   ├── aef-adapters/
│   │   ├── pyproject.toml
│   │   └── src/
│   │       └── aef_adapters/
│   │           └── __init__.py
│   │
│   └── aef-shared/
│       ├── pyproject.toml
│       └── src/
│           └── aef_shared/
│               ├── __init__.py
│               └── logging/
│
├── workflows/                  # Workflow YAML definitions
├── docker/                     # Docker configs
└── docs/                       # Documentation
```

### 4. Root pyproject.toml Pattern

```toml
[project]
name = "agentic-engineering-framework"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "aef-cli",
    "aef-domain",
    "aef-adapters",
    "aef-shared",
]

[tool.uv.workspace]
members = ["apps/*", "packages/*"]

[tool.uv.sources]
aef-cli = { workspace = true }
aef-domain = { workspace = true }
aef-adapters = { workspace = true }
aef-shared = { workspace = true }

[build-system]
requires = ["uv_build>=0.6.0"]
build-backend = "uv_build"
```

### 5. Member Package Pattern

```toml
# packages/aef-domain/pyproject.toml
[project]
name = "aef-domain"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["aef-shared", "pydantic>=2.10.0"]

[build-system]
requires = ["uv_build>=0.6.0"]
build-backend = "uv_build"
```

The source code lives at: `packages/aef-domain/src/aef_domain/`

### 6. Core Commands

```bash
# Lock entire workspace
uv lock

# Install all dependencies
uv sync

# Run specific package
uv run --package aef-cli python -m aef_cli

# Add dependency to specific package
uv add --package aef-domain sqlalchemy
```

## Consequences

### Positive
- Clean separation: project dir ≠ import namespace (hyphen vs underscore)
- `src/` layout prevents import pollution
- Single lockfile ensures dependency consistency
- Fast builds with uv_build
- Each package is independently publishable
- Clear organization: apps/, packages/, lib/

### Negative
- Slightly deeper nesting than flat layout
- Must remember naming convention (hyphens vs underscores)

### Neutral
- `aef-` prefix required for unique package names (publishability)
- Structure is more complex than single-package projects

## References
- [uv Workspaces Documentation](https://docs.astral.sh/uv/concepts/workspaces/)
- [PEP 517 - Build System Interface](https://peps.python.org/pep-0517/)
- [Python src-layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)

