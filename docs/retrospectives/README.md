# Retrospectives

Short post-incident write-ups that link to a concrete change (PR, memory entry, runbook update). If there is no change, the lesson belongs in an "Open follow-ups" bullet under an existing retro, not as a standalone entry.

## Naming

`YYYY-MM-DD-<slug>.md`

## Template

```markdown
# YYYY-MM-DD <title>

## What happened
One paragraph.

## Timeline
- HH:MM - event
- HH:MM - event

## Root cause
What was actually wrong, not the symptom.

## What we changed
- PR #NNN - one-line description
- Memory entry / runbook / docs link

## Open follow-ups
- [ ] Thing we noticed but did not fix yet
```

## Index

| Date | Slug | One-line lesson | Links |
|------|------|-----------------|-------|
| 2026-05-01 | envoy-base-image-rot | Recent upstream tag does not imply working apt sources; build locally before bumping a base image. | [entry](2026-05-01-envoy-base-image-rot.md), PR #740 |
