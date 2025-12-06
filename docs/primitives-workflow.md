# Primitives Workflow

This document describes how to work with Claude commands, tools, and hooks (primitives) in AEF.

## Overview

AEF uses primitives from the `agentic-primitives` library (submodule at `lib/agentic-primitives/`). The workflow supports:

1. **Syncing shared primitives** from `agentic-primitives` → AEF
2. **Creating repo-specific commands** that stay only in AEF
3. **Contributing new primitives** back to `agentic-primitives`

## Directory Structure

```
.claude/
├── .agentic-manifest.yaml    # Tracks what's managed by agentic-primitives
├── commands/
│   ├── devops/               # Category: devops (from AP)
│   │   └── manage-security-patches.md
│   ├── docs/                 # Category: docs (from AP)
│   │   └── doc-scraper.md
│   ├── meta/                 # Category: meta-prompts (from AP)
│   │   ├── create-doc-sync.md
│   │   ├── create-prime.md
│   │   └── prompt-generator.md
│   ├── qa/                   # Category: qa (from AP)
│   │   ├── pre-commit-qa.md
│   │   ├── qa-setup.md
│   │   └── review.md
│   └── sync-event-sourcing.md  # LOCAL: AEF-specific command
├── hooks/
│   ├── handlers/*.py         # Hook handlers (from AP)
│   └── validators/**/*.py    # Hook validators (from AP)
├── mcp.json                  # MCP tool configurations (from AP)
└── settings.json             # Claude settings with hooks (from AP)
```

## How It Works

### Managed vs Local Files

The `.agentic-manifest.yaml` file tracks which files are **managed** (from `agentic-primitives`).

- **Managed files**: Listed in the manifest, updated during sync
- **Local files**: NOT in the manifest, preserved during sync

### Syncing from agentic-primitives

```bash
# Full sync: build + install (preserves local commands)
just primitives-sync

# Check what's managed vs local
just primitives-status

# List only local commands
just primitives-local
```

The sync will:
- ✅ Update all managed primitives to latest versions
- ✅ Add new primitives from `agentic-primitives`
- ✅ **Preserve all local files** (not in manifest)
- ✅ Remove primitives that were deleted upstream (only managed ones)

## Creating Repo-Specific Commands

Simply create a `.md` file in `.claude/commands/`:

```bash
# Create directly at root (no category)
echo "Your command content" > .claude/commands/my-aef-command.md

# Or with a category subdirectory
mkdir -p .claude/commands/aef/
echo "Your command content" > .claude/commands/aef/my-command.md
```

**Convention for AEF-specific commands:**
- Put them at the root level (like `sync-event-sourcing.md`)
- Or create an `aef/` category for AEF-specific commands
- They will be automatically preserved during sync

## Contributing Back to agentic-primitives

If you create a command in AEF that should be shared:

### 1. List Local Commands
```bash
just primitives-local
```

### 2. Create the Primitive in agentic-primitives

```bash
cd lib/agentic-primitives

# Create the primitive structure
mkdir -p primitives/v1/prompts/commands/{category}/{command-name}

# Add the prompt file
cp ../../.claude/commands/your-command.md \
   primitives/v1/prompts/commands/{category}/{command-name}/{command-name}.prompt.v1.md

# Create metadata file
cat > primitives/v1/prompts/commands/{category}/{command-name}/{command-name}.yaml << 'EOF'
id: command-name
kind: command
category: your-category
domain: your-domain
summary: "Brief description"
tags:
  - tag1
  - tag2
tools:
  - Read
  - Grep
versions:
  - version: 1
    file: command-name.prompt.v1.md
    status: draft
    hash: "blake3:placeholder"
    created: "2025-12-06"
    notes: "Initial version"
default_version: 1
EOF

# Validate
./cli/target/debug/agentic-p validate
```

### 3. Submit PR to agentic-primitives

```bash
cd lib/agentic-primitives
git checkout -b feat/add-new-command
git add primitives/
git commit -m "feat(commands): add new-command primitive"
git push origin feat/add-new-command
# Create PR via GitHub
```

### 4. After Merge, Sync Back

```bash
cd ../..  # Back to AEF root
git submodule update --remote lib/agentic-primitives
just primitives-sync
```

Your command will now be managed, and you can delete the local copy if desired.

## Workflow Summary

```
┌─────────────────────────────────────────────────────────────────────┐
│                        agentic-primitives                           │
│  (lib/agentic-primitives/)                                         │
│                                                                     │
│  primitives/v1/prompts/commands/                                   │
│  ├── devops/manage-security-patches/                               │
│  ├── qa/review/                                                    │
│  └── ...                                                           │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ just primitives-sync
                              │ (build + install)
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                              AEF                                    │
│  .claude/                                                          │
│  ├── commands/                                                     │
│  │   ├── devops/manage-security-patches.md  ← MANAGED             │
│  │   ├── qa/review.md                        ← MANAGED             │
│  │   └── sync-event-sourcing.md              ← LOCAL (preserved)   │
│  └── .agentic-manifest.yaml                                        │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ Contribute back
                              │ (manual: copy to AP, add metadata, PR)
                              ▼
                    ┌─────────────────┐
                    │  GitHub PR to   │
                    │ agentic-primitives│
                    └─────────────────┘
```

## Commands Reference

| Command | Description |
|---------|-------------|
| `just primitives-sync` | Build and install primitives from AP (preserves local) |
| `just primitives-status` | Show managed vs local files |
| `just primitives-local` | List local-only commands (contribution candidates) |
| `just primitives-clean` | Clean build artifacts |
| `just primitives-cli-build` | Build the agentic-p CLI |

## Troubleshooting

### "Primitives not installing"
```bash
# Make sure the CLI is built
just primitives-cli-build

# Check if build exists
ls build/claude/
```

### "Local command was overwritten"
This shouldn't happen - local files are preserved. But if it does:
```bash
# Check the manifest
cat .claude/.agentic-manifest.yaml | grep your-command

# If it's in the manifest, it's managed (not local)
# If not in manifest, file a bug report
```

### "Want to stop syncing a managed command"
You can't exclude specific managed commands. Options:
1. Fork `agentic-primitives` and remove it
2. Delete the command after each sync (not recommended)
3. File an issue requesting a feature for exclusion rules
