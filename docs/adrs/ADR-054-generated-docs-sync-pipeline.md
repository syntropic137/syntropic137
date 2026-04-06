# ADR-054: Generated Documentation Sync Pipeline

## Status

Accepted

## Context

The Syntropic137 docs site (`apps/syn-docs/`) serves two categories of generated reference documentation:

1. **CLI Reference** — MDX pages documenting every `syn` CLI command, argument, and option
2. **API Reference** — MDX pages generated from the OpenAPI specification

Both are derived from source code (CLI command definitions, FastAPI route definitions) and must stay in sync. Prior to this ADR:

- CLI docs were generated from the **Python CLI** via Typer/Click introspection, but the Python CLI is deprecated — the published CLI is the Node.js CLI (`@syntropic137/cli`). This caused documented commands to diverge from reality (`syn agent chat` documented but nonexistent, `syn triggers disable` vs actual `disable-all`, installation instructions referencing `uv sync`).
- API docs had no drift detection — changes to API routes could silently desync the published reference.
- No local feedback loop existed — developers only discovered stale docs when CI failed on the `release` branch, far too late in the process.

## Decision

### Single source of truth per doc type

| Doc Type | Source of Truth | Generator | Output |
|----------|----------------|-----------|--------|
| CLI Reference | `apps/syn-cli-node/src/commands/` (TypeScript `CommandDef`/`CommandGroup` types) | `apps/syn-cli-node/scripts/generate-cli-docs.ts` | `apps/syn-docs/content/docs/cli/*.mdx` |
| API Reference | `apps/syn-api/` (FastAPI routes → OpenAPI spec) | `scripts/extract_openapi.py` → `apps/syn-docs/scripts/generate-api-docs.mjs` | `apps/syn-docs/content/docs/api/*.mdx` |

### Generation pipeline

```
CLI commands (CommandDef/CommandGroup)        FastAPI routes
    ↓ tsx scripts/generate-cli-docs.ts            ↓ uv run scripts/extract_openapi.py
content/docs/cli/*.mdx                        openapi.json
                                                  ↓ node scripts/generate-api-docs.mjs
                                              content/docs/api/*.mdx
```

Both outputs are **committed to the repo** — not generated at build time. This ensures:
- Diffs are reviewable in PRs
- Changes are explicit and intentional
- No build-time dependencies on the Python environment for CLI docs (or vice versa)

### Three-layer drift detection

Drift is caught at three progressively earlier points:

| Layer | Trigger | What Runs | Feedback Speed |
|-------|---------|-----------|----------------|
| **Local dev** | `just docs` | CLI docs regenerated before dev server starts | Instant |
| **Local QA** | `just qa` → `docs-sync` | CLI + API docs regenerated, fail if uncommitted changes | Pre-commit |
| **CI** | PR to `release` → `release-gate.yml` `docs-drift` job | CLI + API docs regenerated, fail if diff detected | Pre-merge |

The drift check pattern is identical for both doc types:

```bash
# 1. Regenerate
pnpm --filter @syntropic137/cli generate:docs

# 2. Check for changes
CHANGED=$(git diff --name-only <output-dir>)
UNTRACKED=$(git ls-files --others --exclude-standard <output-dir>)
if [[ -n "$CHANGED" || -n "$UNTRACKED" ]]; then
  echo "Docs are out of sync"
  exit 1
fi
```

### Just recipes

| Recipe | Purpose |
|--------|---------|
| `just docs-cli-gen` | Generate CLI docs (standalone) |
| `just docs` | Generate CLI docs + start dev server |
| `just docs-sync` | Drift check: architecture + CLI + API docs |
| `just docs-site-gen` | Generate CLI + API docs (full site content) |
| `just docs-site-build` | Full site build with all generated content |
| `just qa` | Includes `docs-sync` — catches all drift |

### CLI docs generator design

The TypeScript generator (`apps/syn-cli-node/scripts/generate-cli-docs.ts`) directly imports the same `CommandGroup` and `CommandDef` instances that the CLI registers at startup. It:

1. Imports all command groups + root commands from the shared registry (`src/registry.ts`) — the same single source of truth that `src/index.ts` uses. Adding a new command group to the registry automatically includes it in both the CLI and the generated docs (poka-yoke)
2. Walks `CommandGroup.commands` (public `ReadonlyMap`) to extract metadata
3. Renders MDX with identical format to the previous Python generator (frontmatter, usage blocks, argument/option tables)
4. Writes to `apps/syn-docs/content/docs/cli/`

Handler functions are imported but never called — no side effects, no API connection needed.

## Consequences

### Positive

- **CLI docs always match the published CLI** — generated from the same TypeScript source code that ships to npm
- **API docs always match the running API** — generated from the same FastAPI routes that serve requests
- **Drift caught at three layers** — developers see stale docs in local QA before CI, and CI catches it before release
- **No Python dependency for CLI docs** — CI docs-drift job only needs Node.js/pnpm
- **Diffs are reviewable** — generated docs are committed, so changes appear in PRs
- **Zero-config for developers** — `just docs` auto-generates before starting the dev server

### Negative

- **Generated files in git** — adds ~20 MDX files per doc type to the repository. Accepted tradeoff for reviewable diffs and avoiding build-time generation complexity.
- **Two-step workflow** — developers must run `just docs-cli-gen` (or `just qa`) and commit the result when changing CLI commands. The drift check ensures this isn't forgotten.

## References

- [ADR-053: Plugin Schema Generation Strategy](ADR-053-plugin-schema-generation-strategy.md) — same "generate + commit + drift check" pattern applied to plugin schemas
- Issue [#467](https://github.com/syntropic137/syntropic137/issues/467) — Rewrite CLI docs generation to target Node CLI
- Generator: `apps/syn-cli-node/scripts/generate-cli-docs.ts`
- CI job: `.github/workflows/release-gate.yml` → `docs-drift`
