# ADR-066: Separation of concerns across Syntropic137 components

- **Status**: Accepted
- **Date**: 2026-05-05
- **Issue**: triggered by #726 retro
- **Related**: ADR-001 (architecture overview), ADR-020 (bounded contexts), ADR-024 (workspace setup), ADR-027 (workspace provider images), ADR-040 (ports per bounded context), ADR-055 (projection coordinator), ADR-057 (lifecycle service registry)

## Context

Syntropic137 has multiple runtime components (API, CLI, workspaces, processors, collectors, dashboard, infrastructure services). Without a clear shared rule for "which work belongs in which component," features get placed in whichever tier the agent or human happened to be editing at the time. The #726 retro caught one concrete instance: a `git clone` was placed in the API container request handler, violating the long-standing "thin API wrapper" intent. CLAUDE.md states that intent in two places, but no single document lists the components, their responsibilities, and the "what goes where" rule for cross-cutting concerns. This ADR is that document.

The goal is twofold:

1. Make it easy for any contributor (human or agent) to look up "where should this run?" before they write the code.
2. Give code reviewers a citation when they push back on placements that violate the principle.

## Decision

### Tier responsibilities

| Tier | Component(s) | What it owns | What it MUST NOT do |
|---|---|---|---|
| **API** (HTTP) | `apps/syn-api` | Translate HTTP requests into commands or projection reads, return Pydantic responses, map typed errors to HTTP status codes. Stateless per request. | Long-running work (>~1s), external network calls beyond own DB/cache/storage, subprocess spawns, file system mutation outside `/tmp`, business rules, decision logic. |
| **Domain** | `packages/syn-domain` | Aggregates, events, commands, value objects, ports (interfaces only). Pure logic, deterministic, replay-safe. | I/O of any kind. Direct dependency on adapters or framework code. Imports from `syn-adapters`, `syn-api`, `syn-cli-node`. |
| **Adapters** | `packages/syn-adapters` | Concrete implementations of domain ports: storage, repositories, fetchers, message buses, external API clients. Where the I/O happens. | Business rules. Sneaky reach-back into domain internals. |
| **Application services** | `apps/syn-api/src/syn_api/services/` | Composition of domain handlers, projection reads, and adapter calls into application-level operations. Used by API routes. | Heavy I/O (defer to Processors), git/subprocess (defer to CLI or Workspace). |
| **Processors** | `apps/syn-api/.../processors/`, `slices/execute_workflow/` | Long-running, multi-step orchestration via the To-Do List pattern (see ADR-055). React to events, dispatch commands, persist state via projections. Crash-resilient. | Imperative async/await orchestration. Holding ephemeral state in memory. |
| **CLI** | `apps/syn-cli-node` | User-facing client. Local file/git operations on the user's machine. Interactive prompts. Translates user intent into thin API calls. | Business rules (push them down to domain handlers via API). Persistent state (the API owns persistence). |
| **Workspace** | `lib/agentic-primitives/providers/workspaces/*` | Isolated agent execution. Has the heavy tooling baked in (claude CLI, git, language servers, hooks). Runs the actual agent. | Talking back to the API mid-task (the orchestrator drives, the workspace executes). |
| **Collectors** | `packages/syn-collector` | Event ingestion (webhooks, JSONL streams). Transforms external signals into domain events. | Holding state. Cross-cutting orchestration. |
| **Dashboard UI** | `apps/syn-dashboard-ui` | Read-only display, SSE-driven live updates. | Mutating state directly (always go via API). |
| **Infrastructure** | `infra/`, `docker/`, ` Dockerfile`s | Container build, compose, secrets, networking, port mapping, runtime dependencies. | Application logic. |

### Where common concerns belong

| Concern | Default home | Rationale |
|---|---|---|
| `git clone`, `git fetch`, any subprocess-git | **CLI** (preferred) or **Workspace** | The CLI runs on the user's machine where git, ssh keys, and credentials already exist. Workspaces have git baked into the base image for agent use. The API has neither. |
| Long-running orchestration (multi-step, multi-second) | **Processor** (To-Do List pattern, ADR-055) | Crash-resilient, decoupled from request lifecycle. |
| Real-time queries against projections | **API** | This is what API is for: thin reads and command dispatch. |
| File system mutation on the host | **CLI** or **Workspace** | API runs in a container; host file system access is anti-pattern. |
| Database / cache / object store access | **Adapter** behind a domain **port** | Per ADR-040; keeps the domain pure. |
| Talking to external services (GitHub, npm, registries) | **CLI** for interactive flows; **Adapter** for backend-required flows; **Processor** for long-running fetches | If a user can do it locally, prefer CLI. |
| Computing hashes, formatting display strings | **Domain** if pure, **Adapter** if requires I/O, `*_display` fields in **API responses** for human-readable output (per `feedback_display_in_backend`) | |
| Cross-context coordination | **Anti-corruption layer** (ADR-063) at the boundary | Avoid leaking one bounded context into another. |
| Bootstrap and lifecycle wiring | `_wiring.py`, `lifecycle.py` (ADR-057) | Single composition root per service. |

### How to apply this rule

Before writing code that touches I/O, subprocess, or external services, answer in writing (in the plan or the PR description):

1. **Which tier does this belong in?** Pick from the table above.
2. **Which container will it run in at runtime?** API, CLI, Workspace, Processor, Collector? (For a slice handler, this is determined by who calls it.)
3. **What new dependencies does the runtime image need?** A new subprocess shell-out usually means a Dockerfile update for that image. A new pip dependency usually means a `pyproject.toml` edit.
4. **Does it violate any "MUST NOT" cell in the table above?** If yes, restructure or push it to a different tier.

When this is unclear, prefer the **simpler** placement: CLI for user-facing local work, Adapter behind a port for backend I/O, Processor for anything that takes more than a request cycle.

### Backlinks

Code that implements one of these concerns should reference this ADR in a top-of-file comment:

```python
# See ADR-066: this <thing> lives in the <tier> because <why>
```

This is not enforced by tooling; it is a convention that makes drift easier to spot in review. PR reviewers should challenge any new code that crosses these tier boundaries without an inline citation justifying the choice.

## Consequences

**Positive**

- Clear placement guidance reduces drift and architectural smells.
- Code reviewers gain a single citation ("ADR-066, table row X") rather than relying on tribal knowledge of CLAUDE.md scattered hints.
- New contributors and agents have one document to consult before placing code.
- Future ADRs can extend the table (new tier, new concern) without rewriting the principle.

**Negative**

- Adds a small amount of overhead to feature planning (the four-question check before any I/O work).
- The table will need maintenance as new components are added.
- Some flexibility is lost: an agent who wants to "just call git from the API" will now need to either follow the rule or get explicit approval to deviate.

## Alternatives considered

- **Implicit convention.** The status quo before this ADR. Failed in practice (#726 retro is the proof). Tribal knowledge does not survive contact with sub-agent code generation.
- **Rigid layer enforcement via fitness checks.** A test that imports each module and asserts allowed dependency arrows could enforce "syn-api must not import syn-adapters.git directly," etc. Worth doing later but requires the conceptual rule first; this ADR is the prerequisite.
- **Per-service "what I do" READMEs.** Useful but does not solve cross-service "which service does X" questions, which are the most common source of misplacement.

## Validation

The #726 redesign (sibling document `docs/experiments/cycle-004/dogfood-platform-726/redesign-thin-api.md`) is the first concrete application: git fetch moves out of the API into the CLI, mirroring how `POST /workflows/from-yaml` already works. If that redesign lands cleanly without leaking back into the API, the ADR has done its job.

## References

- CLAUDE.md `#` Thin API wrapper, `#` Processor To-Do List, `#` Two-Lane Architecture
- ADR-001 (architecture overview)
- ADR-020 (bounded contexts and aggregate convention)
- ADR-024 (workspace setup phase)
- ADR-027 (provider-based workspace images, where heavy tooling like git lives)
- ADR-033 (plugin-native workspace images, in agentic-primitives)
- ADR-040 (ports per bounded context)
- ADR-055 (projection coordinator)
- ADR-057 (declarative lifecycle service registry)
- ADR-063 (cross-context anti-corruption layer)
- Retro that triggered this ADR: `docs/experiments/cycle-004/dogfood-platform-726/retro-git-in-api.md`
