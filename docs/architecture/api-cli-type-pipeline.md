# API to CLI Type Pipeline

> Moved verbatim from AGENTS.md / CLAUDE.md (CLAUDE.md diet, owner review). AGENTS.md keeps a one-line summary and a link here.


Single source of truth for the API contract, fully automated:

```
Pydantic models (syn-api/types.py)
  → FastAPI generates OpenAPI spec (/openapi.json)
    → openapi-typescript generates TypeScript types (syn-cli-node/src/generated/api-types.ts)
      → CLI commands use typed client (compile-time path + response validation)
```

**Key files:**
- `apps/syn-api/src/syn_api/types.py` - All response/request models (single source)
- `apps/syn-cli-node/src/generated/api-types.ts` - Auto-generated, never hand-edit
- `apps/syn-cli-node/scripts/generate-types.ts` - Regeneration script
- `apps/syn-cli-node/scripts/check-api-drift.ts` - CI drift detection

**Workflow - adding/changing an endpoint:**
1. Define Pydantic response model in `apps/syn-api/src/syn_api/types.py`
2. Use it as the route return type: `async def list_foos() -> FooListResponse:`
3. Run `just codegen` - regenerates OpenAPI spec, API docs, CLI types, and CLI docs in one step
4. Use the typed client in CLI commands: `import { api } from "../client/typed.js";`

**Rules:**
- CLI field names MUST match API response model field names exactly - never use legacy/alias names
- Domain model field names (e.g. `event`, `repository`) flow through to API responses and CLI - keep them consistent across all three layers
- CI `check:api-drift` fails if generated types are stale
- New CLI commands SHOULD use the typed client (`api.GET`, `api.POST`) - existing commands are being migrated incrementally

