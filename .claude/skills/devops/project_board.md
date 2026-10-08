# Project Board (agent reference)

> Moved verbatim from AGENTS.md / CLAUDE.md (CLAUDE.md diet, owner review). AGENTS.md keeps a one-line summary and a link here.


Work is tracked on the org-level GitHub project board: [Syntropic137 - Launch & Roadmap](https://github.com/orgs/syntropic137/projects/1)

## Structure

- **Milestones** = which phase: `🚀 Open Source Launch` → `🟠 Post-Launch Polish` → `🔵 Scale & Vision`
- **Priority** = urgency within that phase: P0 (critical) → P1 (high) → P2 (medium) → P3 (low)

## For Agents

```bash
# List issues by milestone
gh issue list --repo syntropic137/syntropic137 --milestone "🚀 Open Source Launch"

# Add an issue to the board
gh project item-add 1 --owner syntropic137 --url <issue-url>

# Set priority (requires project item ID from item-add output)
gh project item-edit --project-id PVT_kwDOD5uLBM4BPw_5 --id <item-id> \
  --field-id PVTSSF_lADOD5uLBM4BPw_5zg_Yl2A \
  --single-select-option-id <priority-option-id>
```

**Priority option IDs:** P0=`ceb54537`, P1=`beeef7eb`, P2=`89d84138`, P3=`7e44e913`

## Repos on this board

- `syntropic137/syntropic137` - core platform
- `syntropic137/event-sourcing-platform` - ES foundation
- `syntropic137/syntropic137-claude-plugin` - Claude Code plugin (onboarding, commands, skills)
- `syntropic137/syntropic137-landing-page` - public landing page

## Rules

- Every issue must have a milestone and priority
- P0 = do first, P3 = do last (within each milestone)
- Launch milestone must be clear before open source release

