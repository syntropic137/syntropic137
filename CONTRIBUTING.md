# Contributing to Syntropic137

Thanks for your interest in contributing! This guide covers everything you need to get started.

## Code of Conduct

This project follows the [Contributor Covenant v2.1](CODE_OF_CONDUCT.md). By participating, you agree to uphold these standards.

## Getting Started

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [pnpm](https://pnpm.io/) (Node.js package manager — never npm or yarn)
- [just](https://github.com/casey/just) (task runner)
- Docker and Docker Compose

### Dev Setup

```bash
# Clone with submodules
git clone --recurse-submodules https://github.com/syntropic137/syntropic137.git
cd syntropic137

# Run dev onboarding (sets up .env, deps, submodules, Docker stack)
just onboard-dev

# Start the full dev stack
just dev

# Install git hooks (opt-in — run once after cloning)
just install-hooks
```

### Running QA

```bash
# Full QA suite: lint, format, typecheck, test, coverage, VSA validation
just qa

# Individual checks
just lint          # ruff lint
just format        # ruff format
just typecheck     # pyright (strict mode)
just test          # pytest
```

All checks must pass before submitting a PR.

## Development Workflow

### Branching

- Branch from `main`
- Use conventional branch names: `feat/description`, `fix/description`, `chore/description`, `docs/description`

### Commits

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(orchestration): add phase timeout enforcement
fix(github): deduplicate webhook deliveries
chore(deps): bump ruff to 0.14.7
docs: update self-hosting quickstart
```

Scope is optional but encouraged — use the bounded context name when applicable (`orchestration`, `agent_sessions`, `github`, `artifacts`, `organization`).

### Pull Requests

1. Keep PRs focused — one logical change per PR
2. Fill out the PR template
3. Ensure CI passes (QA + typecheck + tests)
4. PRs are squash-merged

### Code Review

- All PRs require at least one review
- Changes to `.github/`, `docker/`, `infra/`, or `packages/syn-shared/` require maintainer approval (see [CODEOWNERS](.github/CODEOWNERS))

## Code Standards

### Type Safety

We treat Python like TypeScript. Strict type safety everywhere.

- **pyright** must pass (strict mode)
- No `Any` without explicit justification
- No `dict` for structured state — use `@dataclass` or Pydantic `BaseModel`
- Pydantic for all API boundaries, configs, and domain events (`frozen=True`, `extra="forbid"`)
- All public interfaces fully typed

### TODO/FIXME Comments

All TODO and FIXME comments must reference a GitHub issue:

```python
# TODO(#55): Add integration tests
# FIXME(#72): Race condition in projection
```

Never leave a bare `# TODO: ...` without an issue number.

### Testing

- **Unit tests**: Fast, parallel, no infrastructure needed
- **Integration tests**: Use recording-based playback or the ephemeral test stack
- **E2E tests**: Real API calls (used sparingly)

Tests should hit real databases where applicable — no mocking the database layer.

## Architecture

Syntropic137 uses Domain-Driven Design with event sourcing. Before contributing domain logic, familiarize yourself with:

- **Vertical Slice Architecture** — each bounded context is self-contained
- **Processor To-Do List pattern** — for long-running processes (not imperative async loops)
- **Two-lane architecture** — domain events (Lane 1) are separate from observability telemetry (Lane 2)

See the [AGENTS.md](AGENTS.md) file for full architectural details and patterns.

## Reporting Issues

- Use the appropriate [issue template](https://github.com/syntropic137/syntropic137/issues/new/choose)
- Search existing issues first to avoid duplicates
- Include reproduction steps for bugs

## Questions?

Open a [discussion](https://github.com/syntropic137/syntropic137/discussions) or reach out at hello@syntropic137.com.
