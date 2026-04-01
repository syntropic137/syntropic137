# Workflow Packages

Workflow packages are the standard format for distributing pre-built
workflows in Syntropic137. The design follows the Claude Code plugin
marketplace model — packages are self-contained directories that can be
installed from local paths or git repositories.

## Package Formats

### Single Workflow Package

The simplest format — one workflow with its prompt files:

```
my-workflow/
├── workflow.yaml          # Orchestration metadata
├── phases/
│   ├── discovery.md       # Phase prompt (frontmatter + body)
│   └── synthesis.md
└── README.md              # Documentation
```

### Multi-Workflow Plugin

A plugin can bundle multiple workflows with a shared phase library:

```
my-plugin/
├── syntropic137.yaml      # Plugin manifest
├── workflows/
│   ├── research/
│   │   ├── workflow.yaml
│   │   └── phases/*.md
│   └── pr-review/
│       ├── workflow.yaml
│       └── phases/*.md
├── phase-library/         # Shared phases
│   ├── summarize.md
│   └── create-pr.md
└── README.md
```

### Standalone YAML (Legacy)

For backward compatibility, a directory of standalone `.yaml` files is
also supported. This matches the original `workflows/examples/` format.

## Plugin Manifest (`syntropic137.yaml`)

Optional for single-workflow packages, recommended for multi-workflow
plugins. Provides metadata for the installation registry.

```yaml
manifest_version: 1
name: my-plugin
version: "1.0.0"
description: "What this plugin does"
author: your-org           # optional
license: MIT               # optional
repository: https://github.com/org/repo  # optional
```

Unknown fields are silently ignored for forward compatibility.

## Phase Prompt Files (`.md`)

Phase prompts use Claude Code command format — optional YAML frontmatter
followed by the prompt body:

```markdown
---
model: sonnet
argument-hint: "[topic]"
allowed-tools: Read,Glob,Grep,Bash
max-tokens: 4096
timeout-seconds: 300
---

Your prompt text here. Use $ARGUMENTS for the primary input
and {{phase-id}} to reference output from a previous phase.
```

### Frontmatter Keys

| Key | Type | Description |
|-----|------|-------------|
| `model` | string | Claude model to use |
| `argument-hint` | string | Hint shown to users for input |
| `allowed-tools` | string or list | Comma-separated tool names |
| `max-tokens` | int | Max output tokens |
| `timeout-seconds` | int | Phase timeout |

Frontmatter is merged with `workflow.yaml` phase config. **YAML values
take precedence** over frontmatter — use frontmatter for defaults and
YAML for overrides.

## Shared Phases (`shared://`)

Workflows in a multi-workflow plugin can reference shared phases from
the `phase-library/` directory using the `shared://` prefix:

```yaml
phases:
  - id: summarize
    name: Summarize
    order: 3
    prompt_file: shared://summarize    # resolves to phase-library/summarize.md
```

**Copy-on-create semantics:** Shared phase content is resolved at
install time and stored with the workflow. No runtime coupling to the
library — updating a shared phase only affects future installs.

## CLI Commands

### Install

```bash
# From local directory
syn workflow install ./my-package/

# From git repository
syn workflow install https://github.com/org/repo
syn workflow install org/repo                      # GitHub shorthand
syn workflow install org/repo --ref v2.0           # Specific branch/tag

# Dry run (validate without installing)
syn workflow install ./my-package/ --dry-run
```

### Validate

```bash
# Validate a package directory
syn workflow validate ./my-package/

# Validate a single YAML file (existing behavior)
syn workflow validate ./workflow.yaml
```

### Scaffold

```bash
# Single workflow package
syn workflow init ./my-workflow --name "My Workflow" --type research --phases 3

# Multi-workflow plugin
syn workflow init ./my-plugin --name "My Plugin" --multi --type research
```

### List Installed

```bash
syn workflow installed
```

## Installation Flow

1. **Detect source** — local path, git URL, or GitHub shorthand
2. **Clone** (if remote) — `git clone --depth=1` to temp directory
3. **Detect format** — single, multi, or standalone YAML
4. **Resolve prompts** — load `.md` files, merge frontmatter, resolve `shared://`
5. **POST to API** — each resolved workflow → `POST /api/v1/workflows`
6. **Record** — append to `~/.syntropic137/workflows/installed.json`

## Claude Code Marketplace Alignment

This package format is designed to align with Claude Code's plugin
ecosystem:

| Concept | Claude Code | Syntropic137 |
|---------|-------------|--------------|
| Registry | `marketplace.json` | Future: `registry.yaml` |
| Package | `.claude-plugin/plugin.json` | `syntropic137.yaml` |
| Install | `plugin install name@marketplace` | `syn workflow install source` |
| Content | skills, agents, hooks, MCP | workflows, phases, phase-library |

The `syntropic137.yaml` manifest intentionally uses `extra="ignore"` so
future fields (dependencies, permissions, registry metadata) can be
added without breaking existing packages.

## Future Work

- **Registry management** — `syn workflow registry add/list/remove`
- **Package publishing** — `syn workflow publish`
- **Version conflict detection** — `--force` / `--upgrade` flags
- **Marketplace UI** — web browsing and discovery
- **Private git authentication** — `--token` for private repos
