# Findings ledger

**Append-only.** One row per discovered finding across all cycles. Findings never get edited; if superseded, mark the row and add a new row pointing to the superseder.

**How findings flow:**
1. A dogfood pass (or any experiment) produces a result
2. If the result is novel and actionable, it's a finding — add a row here, link to the per-finding evidence file
3. If the finding promotes or supersedes a recommendation, update `CURRENT-BESTS.md` and link both ways
4. Findings are immutable once added; the `Status` column tracks whether they're active or superseded

**How to read:** filter by `Status: active` to see what currently informs recommendations. Filter by `Track` to see findings relevant to one handoff track.

| ID | Date | Cycle | Title | Status | Track | Promotes? | Evidence |
|---|---|---|---|---|---|---|---|
| F1 | 2026-04 | 3 | (cycle 3 F1 — see findings/F1-*.md) | active | platform | — | `cycle-003/findings/F1-*.md` |
| F2 | 2026-04 | 3 | Parallel Task fan-out drops outputs | **superseded** | platform | superseded by F1-c4 | `cycle-003/findings/F2-*.md` |
| F3 | 2026-04 | 3 | Verified-grounded plans need repos passed | active | sdlc | — | `cycle-003/findings/F3-*.md` |
| F4 | 2026-04 | 3 | One-deliverable-per-phase shape mitigates F2 | **superseded** | sdlc | superseded by F1-c4 (root cause is platform, not shape) | `cycle-003/findings/F4-*.md` |
| F5 | 2026-04 | 3 | Sonnet honors multi-phase contract | active | sdlc | superseded by F8 as default | `cycle-003/findings/F5-*.md` |
| F6 | 2026-04 | 3 | (cycle 3 F6) | active | — | — | `cycle-003/findings/F6-*.md` |
| F7 | 2026-04 | 3 | Workspace state not cross-phase | active | platform | — | `cycle-003/findings/F7-*.md` |
| F8 | 2026-04 | 3 | Frontier only needed on synthesis | **active** | sdlc | promoted `plan-multiphase-routed-haiku-opus-v1` as default plan workflow | `cycle-003/findings/F8-*.md` |
| F1-c4 | 2026-05-02 | 4 | Platform stores one primary artifact per phase (root cause) | **active** | platform / artifacts | reframed #749, bundled into #758 fix scope, drove "phase-per-artifact" recommendation | `cycle-004/tick-loop-shape/RESULTS.md` |
| F2-c4 | 2026-05-02 | 4 | Cron not natively possible inside workspace | active | platform | added "known limitation" — three paths if pursued | `cycle-004/cron-feasibility/RESULTS.md` |
| F3-c4 | 2026-05-02 | 4 | Null bytes in agent output crash event ingestion | **active** | platform | filed in `20260502_platform.md` | `cycle-004/claude-p-feasibility/RESULTS.md` |
| F4-c4 | 2026-05-02 | 4 | claude-p orchestrator pattern works (parent + N parallel children + wait) | **active** | sdlc / platform | promoted as orchestrator pattern in CURRENT-BESTS, filed OAuth-export platform ask | `cycle-004/claude-p-feasibility/RESULTS-v2.md` |
| F5-c4 | 2026-05-02 | 4 | Workspace SDLC capability baseline + 3 platform asks | **active** | platform | refined #750 with three concrete sub-asks | `cycle-004/sdlc-capabilities/RESULTS.md` |
| F6-c4 | 2026-05-02 | 4 | Playwright feasible in workspace + 27-lib gap | **active** | platform / sdlc | filed browser-libs platform ask | `cycle-004/playwright-feasibility/RESULTS.md` |
| F7-c4 | 2026-05-02 | 4 | Subagent_completed events not recorded | active | platform | noted alongside F1-c4 | `cycle-004/claude-p-feasibility/RESULTS.md` |
| F8-c4 | 2026-05-02 | 4 | SSE endpoints exist; polling was wasteful | **active** | platform / experiments | promoted SSE as recommended watch pattern in CURRENT-BESTS | (this conversation; OpenAPI spec) |

## When a pass creates a new workflow

If a pass creates an experimental workflow, the finding row should:

- **Link to the workflow ID** in the Title or Notes column so future readers can find it
- Note in **Promotes?** whether the new workflow is being promoted to default, kept as an override option, or marked for deletion after the experiment

If the experimental workflow is not promoted, it can either stay as an override option in `CURRENT-BESTS` (with the finding linked) or be cleaned up. Stale workflow inventory should be flagged in the cycle's `BOTTLENECKS.md`.

## Conventions

- **ID:** `F<N>-c<cycle>` for findings discovered in cycle N+. Cycle 3 used `F<N>` without a cycle suffix; preserved as-is.
- **Status:** `active` (still informs current recommendations), `superseded` (replaced by a newer finding — link in Promotes column), `inactive` (was active but circumstances changed; not actively used).
- **Promotes?:** what changed in `CURRENT-BESTS.md` because of this finding, or which earlier finding it superseded.
- **Evidence:** path to the per-finding writeup. Never delete the writeup even after supersession — it's the audit trail.

## What lives where

- **`CURRENT-BESTS.md`** = "what should I use today" (mutable, current state synthesis)
- **`FINDINGS-LEDGER.md`** = "what have we learned" (append-only history)
- **Per-finding files in `cycle-NNN/...`** = "the actual evidence" (immutable per-cycle artifacts)
- **`cycle-NNN/README.md`** = "what was the cycle about + parameters" (per-cycle, mutable during the cycle)
- **`docs/runbooks/003-syntropic-assisted-dogfooding.md`** = "the loop" (long-lived, generic, references CURRENT-BESTS by pointer)
