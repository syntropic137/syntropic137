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
| 2026-08-17 | green-checks-that-check-nothing | Absence of verification looks identical to successful verification. A gate must publish a census and something must assert it. | [entry](2026-08-17-green-checks-that-check-nothing.md), #825, #821 |
| 2026-10-04 | dogfood-orchestrator-day | The platform's limits were invisible until a paid run hit them; hold the orchestrator to the same standards (verify state, never block on a question). | [entry](2026-10-04-dogfood-orchestrator-day.md), #1581, #1582, ESP #337 |
| 2026-10-06 | merge-down-and-the-dropped-start | A green test double proves the double; four PRs passed against in-memory fakes and failed against the real store, so a second verifier and a real-backend gate are not optional. | [entry](2026-10-06-merge-down-and-the-dropped-start.md), #1641, #1644, #1652, ESP #344 |
