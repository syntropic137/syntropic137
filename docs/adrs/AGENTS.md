# ADR Directory — Agent Instructions

Check [README.md](README.md) for the categorized index of all Architecture Decision Records.

## Creating a New ADR

- Next available number: **ADR-056**
- Follow the Nygard template: Status → Date → Context → Decision → Consequences
- After creating, add an entry to README.md in the appropriate category
- Keep the filename format: `ADR-NNN-short-kebab-title.md`
- All TODO/FIXME comments in the ADR body must reference a GitHub issue: `TODO(#NNN):`

## Numbering Notes

- **ADR-025** was never created (numbering gap — do not reuse)
- **ADR-027** has two variants: `sdk-wrapper-architecture` (superseded) and `unified-workflow-executor` (accepted)
- **ADR-035** has two variants: `conversation-storage-architecture` (proposed) and `qa-workflow-standard` (accepted)

## Status Values

Use one of: `Proposed`, `Accepted`, `Superseded`, `On Hold`, `Implemented`

## Related ADR Directories

- Event Sourcing Platform: `lib/event-sourcing-platform/docs/adrs/`
- agentic-primitives: `lib/agentic-primitives/docs/adrs/`
