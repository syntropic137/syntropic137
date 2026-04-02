# ADR-052: Plugin Schema Generation Strategy

## Status

Accepted

## Context

The Syntropic plugin system defines five file formats that plugin authors must conform to:

1. `workflow.yaml` — Workflow definitions with phases and inputs
2. `triggers.json` — Embedded trigger definitions per workflow
3. `syntropic137-plugin.json` — Plugin manifest metadata
4. `marketplace.json` — Marketplace registry index
5. `phase-frontmatter` — Phase frontmatter blocks embedded in Markdown content

Plugin authors need to know the valid schema for these formats. Without formal schemas, authors rely on examples and trial-and-error. Editors can't provide autocomplete. The CLI can't give meaningful validation errors.

Additionally, the schema must stay in sync across:
- **syn-domain** (Pydantic models for workflow/phase definitions)
- **syn-cli** (Pydantic models for plugin manifest, marketplace index)
- **syn-cli-node** (Zod schemas in the Node.js CLI port)
- **syn-api** (API validation at install/import time)
- **Editor tooling** (VS Code, JetBrains via JSON Schema)
- **Marketplace repos** (CI validation of contributed plugins)

## Decision

### Pydantic models are the single source of truth

All plugin format schemas are defined as Pydantic `BaseModel` classes in the Python codebase. JSON Schemas are generated from these models via `BaseModel.model_json_schema()` and committed to `schemas/plugin/` in the repository root.

### Schema generation pipeline

```
Pydantic models (source of truth)
    ↓ scripts/export_plugin_schemas.py
schemas/plugin/*.schema.json (committed, versioned)
    ↓ consumed by
├── syn workflow validate (CLI validation)
├── syn-api (already validates via Pydantic at import time)
├── syn-cli-node (Zod schemas must conform — tested in CI)
├── Editor tooling ($schema reference in files)
├── Marketplace repos ($schema URL for CI validation)
└── Documentation (schema reference on docs site)
```

### Schema versioning

Schemas include a top-level `$id` with the platform version:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://syntropic137.dev/schemas/plugin/v0.18/workflow.schema.json",
  ...
}
```

The version in the `$id` is the **schema version**, which tracks the platform version at time of schema change. Not every platform release changes the schema — the version only bumps when the format itself changes.

### Staleness detection

CI runs the export script and diffs the output against the committed schemas. If they diverge, the build fails. This prevents Pydantic model changes from silently drifting from the published schemas.

### Trigger schema

The domain's `TriggerCondition` and `TriggerConfig` are frozen dataclasses (domain value objects), not Pydantic models. A dedicated Pydantic model (`TriggerFileSchema`) defines the distributable `triggers.json` format. This model is the source of truth for the trigger file schema — it is separate from the domain aggregate which handles runtime trigger behavior.

### Where schemas live

```
schemas/
  plugin/
    workflow.schema.json          # From WorkflowDefinition
    triggers.schema.json          # From TriggerFileSchema (new)
    plugin-manifest.schema.json   # From PluginManifest
    marketplace.schema.json       # From MarketplaceIndex
    phase-frontmatter.schema.json # From PhaseYamlDefinition (subset)
```

Top-level `schemas/` because these are cross-cutting — used by CLI, API, docs, editor tooling, and external marketplace repos.

## Consequences

### Positive

- **Single source of truth** — Pydantic models define the format, everything else derives from them
- **No drift** — CI enforces schema freshness
- **Editor support** — JSON Schema enables autocomplete in VS Code/JetBrains for free
- **Cross-platform validation** — Node.js CLI (Zod), Python CLI (Pydantic), and external tools all validate against the same schema
- **Plugin author DX** — `$schema` in files gives instant feedback without running the CLI

### Negative

- **Build step required** — Schema generation must run when models change
- **Trigger model duplication** — `TriggerFileSchema` (Pydantic) is a parallel definition to `TriggerCondition`/`TriggerConfig` (dataclasses). Changes to either must be kept in sync manually. This is acceptable because the domain model (aggregate behavior) and the distributable format (file schema) serve different purposes and may intentionally diverge.

## References

- [Pydantic JSON Schema generation](https://docs.pydantic.dev/latest/concepts/json_schema/)
- [JSON Schema specification](https://json-schema.org/draft/2020-12/json-schema-core)
- ADR-001 s6, ADR-032: Type safety standards
- syntropic137/syntropic137#436: CLI port to Node.js
