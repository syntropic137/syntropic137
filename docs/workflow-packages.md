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

## Skills (`skills:`)

A workflow can declare agent skills at workflow scope (every phase) and at
phase scope (that phase only). The lists merge. Two sources are supported:

```yaml
# Workflow scope: applies to every phase.
skills:
  - ./skills/repo-conventions                    # VENDORED: a directory in the plugin

phases:
  - id: investigate
    name: Investigate
    order: 1
    skills:
      # EXTERNAL: org/repo/skill-name@version, cloned at install time.
      - anthropics/skills/doc-coauthoring@3b3fad96af16a10759d930941b4520ba0c40edae
```

- A vendored skill is a directory containing `SKILL.md`. It has no version of
  its own, so `syn workflow install` pins it by the sha256 of its file tree and
  uploads a definition in which every ref is explicitly pinned.
- An external ref must be pinned to a tag, branch, or commit sha. `@latest` is
  rejected for reproducibility.
- Registration identity is `(source_url, version, skill_name)`. A ref whose
  content hash is already stored performs no upload.
- A phase that declares skills fails if they cannot be installed. It never runs
  silently without them.

Worked example, including per-phase divergence:
[`workflows/examples/starter-plugin/`](../workflows/examples/starter-plugin/README.md).

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

### Export

```bash
# Export as installable package
syn workflow export <workflow-id> --output ./my-package/

# Export as Claude Code plugin
syn workflow export <workflow-id> --format plugin --output ./my-plugin/
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
| Registry | `marketplace.json` | `marketplace.json` (same format) |
| Package | `.claude-plugin/plugin.json` | `syntropic137.yaml` / `syntropic137-plugin.json` |
| Install | `plugin install name@marketplace` | `syn workflow install <name>` |
| Discovery | marketplace search | `syn workflow search` / `syn workflow info` |
| Content | skills, agents, hooks, MCP | workflows, phases, phase-library |

The `syntropic137.yaml` manifest intentionally uses `extra="ignore"` so
future fields (dependencies, permissions, registry metadata) can be
added without breaking existing packages.

## Exporting Workflows

Export reverses the install flow — taking a running workflow from the
API and producing an installable package directory.

### CLI

```bash
# Export as package (default)
syn workflow export <workflow-id> --output ./my-package/

# Export as Claude Code plugin
syn workflow export <workflow-id> --format plugin --output ./my-plugin/
```

### API

```
GET /api/v1/workflows/{id}/export?format=package|plugin
```

Returns a JSON manifest with `files: dict[str, str]` mapping relative
paths to file contents. The CLI writes these to disk.

### Export Flow

1. **Fetch workflow** — `GET /api/v1/workflows/{id}` (via projection)
2. **Decompose phases** — each phase's `prompt_template` becomes a `.md`
   file with kebab-case YAML frontmatter (`argument-hint`, `allowed-tools`,
   `max-tokens`, `timeout-seconds`)
3. **Generate workflow.yaml** — uses `prompt_file: phases/{id}.md`
   references (not inline `prompt_template`)
4. **Plugin extras** (if `--format plugin`) — generate `syntropic137.yaml`
   manifest and a Claude Code command wrapper in `commands/`
5. **Write to disk** — CLI creates the directory structure

### Round-Trip Guarantee

Exported packages MUST be re-importable via `syn workflow install`.
This is enforced by:

- Phase frontmatter using the same kebab-case keys that
  `md_prompt_loader.py` reads on import
- `workflow.yaml` using `prompt_file:` references that
  `WorkflowDefinition.from_file()` resolves
- Automated round-trip tests: export → `resolve_package()` → compare

### Claude Code Command Wrapper

Plugin exports auto-generate a CC command `.md` file:

```markdown
---
model: sonnet
argument-hint: "<task>"
allowed-tools: Bash
---

# /syn-{slug} — Run {Name} Workflow

Execute the {slug} workflow via Syntropic137:

\`\`\`bash
syn workflow run {workflow-id} --task "$ARGUMENTS"
\`\`\`
```

## Marketplace

Workflow marketplaces are GitHub repositories with a `marketplace.json`
index at the root. Users register marketplaces, then install plugins by
name.

### `marketplace.json` Schema

```json
{
  "name": "my-marketplace",
  "syntropic137": {
    "type": "workflow-marketplace",
    "min_platform_version": "0.0.0"
  },
  "plugins": [
    {
      "name": "research-toolkit",
      "source": "./plugins/research-toolkit",
      "version": "1.2.0",
      "description": "Deep research workflows",
      "category": "research",
      "tags": ["multi-phase", "synthesis"]
    }
  ]
}
```

**Required fields:**
- `name` — marketplace display name (also used as default registry name)
- `syntropic137.type` — must be `"workflow-marketplace"`
- `plugins[].name` — unique plugin identifier
- `plugins[].source` — relative path to plugin directory (no `..` or absolute paths)

**Optional fields:**
- `syntropic137.min_platform_version` — minimum platform version (default `"0.0.0"`)
- `plugins[].version` — semver (default `"0.1.0"`)
- `plugins[].description` — shown in search results
- `plugins[].category` — filterable category (e.g., `"research"`, `"ci"`)
- `plugins[].tags` — filterable tags list

### Security

- Plugin `source` paths are validated against path traversal (`..`, absolute
  paths) before cloning
- Registry names are sanitized — must match `^[a-zA-Z0-9][a-zA-Z0-9._-]*$`
  and cannot contain `..`
- Marketplace indexes are fetched via shallow `git clone` (same as package
  install)

### Caching

- Indexes cached at `~/.syntropic137/marketplace/cache/<name>.json`
- Default TTL: 4 hours
- Force refresh: `syn marketplace refresh`
- Stale or corrupt caches are silently re-fetched

### CLI Commands

```bash
# Registry management
syn marketplace add org/repo [--ref branch] [--name alias]
syn marketplace list
syn marketplace remove <name>
syn marketplace refresh [name]

# Discovery
syn workflow search "query" [--category cat] [--tag tag]
syn workflow info <plugin-name>

# Install / update / uninstall
syn workflow install <plugin-name>
syn workflow update <package-name> [--ref ref] [--dry-run]
syn workflow uninstall <package-name> [--keep-workflows]
```

### Private Repositories

Private GitHub repos work as marketplaces if git can authenticate via
your local credential configuration (SSH keys, `gh auth`, credential
helpers). No special CLI flags are needed.

## Future Work

- **Package publishing** — `syn workflow publish`
- **Version conflict detection** — `--force` / `--upgrade` flags
- **Marketplace UI** — web browsing and discovery in the dashboard
- **Dependency resolution** — plugins declaring dependencies on other plugins
- **Rollback** — `syn workflow update --rollback` to revert to previous version
