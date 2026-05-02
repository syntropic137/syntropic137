# ADR-061: Justfile Script Extraction

- **Status:** Accepted
- **Date:** 2026-04-11
- **Context:** Justfile maintainability, testability, and reuse

## Problem

The justfile has grown to ~1900 lines with 158 recipes and 36 embedded scripts.
Several recipes contain substantial inline logic (the largest, `onboard-dev`, is
308 lines). This causes several problems:

1. **Untestable.** Inline bash/python in a justfile cannot be unit tested. Logic
   bugs are only caught by running the full recipe manually.
2. **Not composable.** Two recipes that need shared logic must duplicate it or
   call each other (creating implicit ordering dependencies in the justfile).
3. **Hard to review.** A 300-line embedded script inside a recipe is harder to
   read, diff, and review than a standalone file with proper syntax highlighting.
4. **Fragile.** Justfile quoting rules differ from normal shell. Multi-line
   scripts hit edge cases around variable interpolation (`{{` vs `$`),
   heredocs, and error handling that don't exist in standalone scripts.

## Decision

**Extract non-trivial logic into standalone scripts. Keep the justfile as a thin
dispatch layer.**

### Rules

1. **One-liners stay.** A recipe that runs a single command (or a short pipeline)
   belongs in the justfile. No extraction needed.

   ```just
   lint:
       uv run ruff check .

   env-up branch:
       {{_env}} up "{{branch}}"
   ```

2. **Multi-step logic goes to a script.** If a recipe has control flow (if/else,
   loops, error handling), embedded scripts (shebang lines), or exceeds ~15 lines,
   extract it to `infra/scripts/` (Python) or `scripts/` and call it from a
   one-liner recipe.

   ```just
   # Before (bloated)
   onboard-dev *flags:
       #!/usr/bin/env bash
       set -euo pipefail
       # ... 300 lines of setup logic ...

   # After (thin wrapper)
   onboard-dev *flags:
       uv run python infra/scripts/onboard_dev.py {{flags}}
   ```

3. **Python over bash for anything non-trivial.** Python scripts are easier to
   test, type-check (pyright), and lint (ruff). Bash is fine for simple
   wrappers but not for logic.

4. **Scripts must be independently runnable.** Each extracted script should work
   when called directly (`python infra/scripts/foo.py --help`), not only through
   the justfile. This enables testing and programmatic use by agents.

5. **Justfile recipes are the public API.** Users and docs reference `just <recipe>`.
   Scripts are implementation details. The justfile header and `just --list` are
   the discovery mechanism.

### Directory convention

| Location | Purpose |
|---|---|
| `infra/scripts/` | Infrastructure and environment management (env_manager.py, setup, secrets) |
| `scripts/` | Build, CI, codegen, and validation scripts |

### Existing examples of this pattern

| Recipe | Script | Lines saved |
|---|---|---|
| `env-up`, `env-down`, `env-list`, ... | `infra/scripts/env_manager.py` | ~200 (avoided) |
| `check-compose` | `scripts/generate_published_compose.py` | ~150 |
| `docs-sync` | `scripts/generate-architecture-docs.py` | ~100 |
| `codegen` | `scripts/generate-types.ts` | ~80 |

### Migration priority

Extract the worst offenders first. No need to boil the ocean.

| Recipe | Current lines | Priority |
|---|---|---|
| `onboard-dev` | 308 | P0 - already tracked as #185 |
| `_env-check` | 84 | P1 |
| `_selfhost-preflight` | 78 | P1 |
| `dev-fresh` | 70 | P2 |
| `dev` | 65 | P2 |
| `e2e-smoke` | 59 | P2 |

## Consequences

### Positive

- **Testable.** Extracted scripts can have unit tests (pytest, vitest) covering
  edge cases that are impossible to test through the justfile.
- **Type-safe.** Python scripts run through pyright. Inline bash does not.
- **Composable.** Scripts can import shared utilities, accept arguments, and be
  called from multiple recipes or by agents directly.
- **Reviewable.** Standalone files get proper syntax highlighting, blame history,
  and focused diffs.
- **Smaller justfile.** Recipes become self-documenting one-liners. `just --list`
  tells the full story.

### Negative

- **Indirection.** Reading a recipe requires following a reference to another file.
  Mitigated by good naming (`env_manager.py` is obvious) and keeping the justfile
  recipe comments descriptive.
- **Migration effort.** Extracting 300-line recipes takes time. Mitigated by doing
  it incrementally, prioritized by pain.

## Related

- Issue #185 - Refactor setup.py / onboard-dev (308 lines)
- ADR-060 - On-demand environments (first use of this pattern with env_manager.py)
