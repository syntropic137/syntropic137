"""Plugin schema models — source of truth for all plugin file formats.

These Pydantic models define the canonical schemas for:
- workflow.yaml (WorkflowDefinition)
- triggers.json (TriggerFileSchema)
- syntropic137-plugin.json (PluginManifest)
- marketplace.json (MarketplaceIndex)
- phase-frontmatter (PhaseYamlDefinition)

JSON Schemas are generated from these models via:
    uv run python scripts/export_plugin_schemas.py

The generated schemas live at schemas/plugin/*.schema.json and are:
- Committed to the repo (versioned with the platform)
- Consumed by syn-cli, syn-cli-node (Zod), editor tooling, and CI
- Validated for staleness in CI (re-generate and diff)

See ADR-053 for the full strategy.
"""
