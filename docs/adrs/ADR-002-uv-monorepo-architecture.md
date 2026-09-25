# ADR-002: uv Monorepo Architecture

## Status
Accepted

## Date
2025-12-01

## Context

We need a clean, scalable Python monorepo structure for the Syntropic137. After researching uv's workspace capabilities, we've identified the canonical patterns for Python monorepos.

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
| Project name (pyproject.toml) | **hyphens** | `syn-domain` |
| Import namespace (src/ folder) | **snake_case** | `syn_domain` |
| Installation | same as project | `uv add syn-domain` |
| Import in code | same as namespace | `import syn_domain` |

This mapping is canonical and avoids "hyphen in import path" errors.

### 3. Directory Structure

```
syntropic137/
├── pyproject.toml              # Workspace root
├── uv.lock                     # Single lockfile for all members
├── justfile                    # Task runner
│
├── lib/                        # Git submodules (external deps)
│   ├── agentic-workspace/
│   └── event-sourcing-platform/
│
├── apps/                       # Deployable applications
│   └── syn-cli/
│       ├── pyproject.toml
│       └── src/
│           └── syn_cli/
│               ├── __init__.py
│               ├── main.py
│               └── commands/
│
├── packages/                   # Reusable libraries
│   ├── syn-domain/
│   │   ├── pyproject.toml
│   │   └── src/
│   │       └── syn_domain/
│   │           ├── __init__.py
│   │           └── contexts/
│   │
│   ├── syn-adapters/
│   │   ├── pyproject.toml
│   │   └── src/
│   │       └── syn_adapters/
│   │           └── __init__.py
│   │
│   └── syn-shared/
│       ├── pyproject.toml
│       └── src/
│           └── syn_shared/
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
name = "syntropic137"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "syn-cli",
    "syn-domain",
    "syn-adapters",
    "syn-shared",
]

[tool.uv.workspace]
members = ["apps/*", "packages/*"]

[tool.uv.sources]
syn-cli = { workspace = true }
syn-domain = { workspace = true }
syn-adapters = { workspace = true }
syn-shared = { workspace = true }

[build-system]
requires = ["uv_build>=0.6.0"]
build-backend = "uv_build"
```

### 5. Member Package Pattern

```toml
# packages/syn-domain/pyproject.toml
[project]
name = "syn-domain"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["syn-shared", "pydantic>=2.10.0"]

[build-system]
requires = ["uv_build>=0.6.0"]
build-backend = "uv_build"
```

The source code lives at: `packages/syn-domain/src/syn_domain/`

### 6. Core Commands

```bash
# Lock entire workspace
uv lock

# Install all dependencies
uv sync

# Run specific package
uv run --package syn-cli python -m syn_cli

# Add dependency to specific package
uv add --package syn-domain sqlalchemy
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
- `syn-` prefix required for unique package names (publishability)
- Structure is more complex than single-package projects

## References
- [uv Workspaces Documentation](https://docs.astral.sh/uv/concepts/workspaces/)
- [PEP 517 - Build System Interface](https://peps.python.org/pep-0517/)
- [Python src-layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)

