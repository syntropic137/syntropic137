# ADR-064: Observability Monitor UI for Sessions and Executions

## Status

**Proposed** - 2026-04-18

## Context

The dashboard's `/sessions` and `/executions` pages are the primary human-facing surface for live agent observability. Today they fall short on three counts:

1. **Not live.** `useSessionList` fetches once on mount with no polling and no SSE subscription, so newly-started sessions only appear after a manual refresh. `useExecutionList` polls at 5s intervals while something is running, which is better but still not push-driven and creates unnecessary load when idle.
2. **ID-centric, not run-centric.** Both pages surface raw UUIDs as primary text (e.g. `SessionList.tsx:30`, `ExecutionList.tsx:50`). UUIDs are not how a human identifies a run; the workflow name + phase + start time are. IDs should be a copy-on-demand artifact, not a default column.
3. **Inconsistent and analysis-hostile.** Sessions render as cards (one per row, sparse), Executions render as a fixed 9-column grid. Neither supports sort, multi-select, column visibility, or any structured way to lift a set of runs into another tool (Claude Code, a spreadsheet) for deeper analysis. The two pages share 90% of their information architecture but share no UI primitives.

This ADR establishes a single design and shared component for both pages, defines the live-update contract on top of the existing SSE infrastructure (ADR-049), and records the scalability ceiling we are accepting.

### What this ADR is not

- It does not change the SSE protocol or transport (settled in ADR-049).
- It does not introduce a charting / timeline visualisation. That is a follow-up.
- It does not redesign the Session or Execution detail pages. Only the list views.

### Responsive design

The monitor is reachable from phones as well as desktops — agents produce work at all hours and the common "is that long run finally done?" check happens on whatever screen is nearest. The dashboard uses Tailwind's default breakpoints:

| Breakpoint | Min width | Role |
|---|---|---|
| (base) | 0 | Single column, drawer nav, card list |
| `sm` | 640 | Filter row inline |
| `md` | 768 | Sidebar pinned, table view, hover affordances |
| `lg` | 1024 | Full-density table |

Two specific conventions follow from the table-vs-phone tension:

- **Table becomes a card list below `md:`.** Eight columns are illegible at 375px and horizontal scroll is hostile. Above `md:` the table is the canonical layout; below, each row renders as a card with a 2×2 metric grid. Both views share the same data contract and selection state.
- **Hover-only affordances must have a touch equivalent.** The Copy-ID button on each row is `invisible group-hover:visible` at `md:+` but always visible at `<md:` so touch users can reach it. Tap targets on mobile are ≥44×44.

## Decision

Adopt a **live, table-based observability monitor** built on a single shared `ResourceTable` primitive, used by both Sessions and Executions, fed by a single shared SSE activity stream.

### 1. Mental model: monitor, not admin grid

The list pages serve three jobs in priority order:

1. **Watch** — peripheral attention to running work; is anything stuck or burning tokens?
2. **Triage** — something failed; scan, identify, click in.
3. **Analyse** — compare runs, isolate the expensive ones, hand them to Claude Code.

The design optimises for all three. Most table UIs only serve job 3.

### 2. Design principles

| Principle | What it means in practice |
|---|---|
| Time is the spine | Default sort is recency. Live items pin to the top; new rows fade in. |
| IDs are tools, not subjects | UUIDs hidden by default. Available behind hover-to-copy and a column-toggle opt-in. |
| Density with progressive disclosure | Dense table rows. Secondary fields opt-in via column toggle. Inline expand-row for quick detail; full page for deep dive. |
| Comparable formatting | `1.2k` not `1,237`. `$0.04` not `$0.0438`. `2m 14s` not `134.2s`. Right-aligned monospace numbers. |
| State you can feel | Status as a left-edge color stripe on each row. Running rows shimmer subtly. Completion flashes briefly. |
| Multi-select is a mode | Checking a row reveals a sticky bottom action bar with selection-aggregate metrics and copy/open actions. |
| Filter chips, not just dropdowns | Status as a chip bar with live counts: `[All 47] [Running 2] [Failed 1]`. One click filters and communicates state. |
| Time window is the most important filter | `Last 1h / 24h / 7d / All` defaulting to 24h. Most observability UIs bury this. |
| Live indicator means something | Connection-state pill: green = SSE connected, amber = polling fallback, red = stale. |

### 3. `ResourceTable` shared primitive

A single React component, configured per-page by a column config object:

```typescript
interface ColumnDef<T> {
  id: string
  header: string
  accessor: (row: T) => unknown
  cell?: (row: T) => ReactNode
  sortable?: boolean
  defaultVisible?: boolean
  align?: 'left' | 'right'
}

interface ResourceTableProps<T> {
  rows: T[]
  columns: ColumnDef<T>[]
  rowId: (row: T) => string
  statusAccessor: (row: T) => StatusKind  // drives left-edge color stripe
  onRowClick?: (row: T) => void
  expandRow?: (row: T) => ReactNode
  selection: SelectionAPI<T>             // multi-select state hook
  liveTimerColumns?: string[]            // columns that tick for running rows
}
```

The table owns: sort state (column-header click), column visibility (gear-menu toggle), multi-select state (checkbox per row + select-all-visible), expand-row state, sticky action bar, and live row-level patching (apply event to row in place without re-rendering the whole table).

The table does not own: data fetching, SSE subscription, time-window filter (those live in the page hook).

### 4. Column configurations

**Sessions, default visible (8):**

| Status | Workflow | Phase | Model | Tokens | Cost | Duration | Started |
|---|---|---|---|---|---|---|---|

**Sessions, opt-in (column-toggle menu):**

Session ID, Execution ID, Provider, CLI version (deferred until API exposes it), Subagent count, Turns, Cache hit %, Tools used count

**Executions, default visible (8):**

| Status | Workflow | Progress | Tokens | Cost | Tools | Duration | Started |
|---|---|---|---|---|---|---|---|

**Executions, opt-in:**

Execution ID, Workflow ID, Repos, Phase count, Started timestamp (absolute)

### 5. Selection action bar

Sticky bottom bar appears when selection is non-empty:

```
3 selected   136k tokens   $0.62 total   avg 2m 14s   [Copy for Claude] [Copy IDs] [Open all] [Clear]
```

Aggregates are computed client-side from selected rows. Selection persists across filter and sort changes, tracked by row ID. If the active filter hides a selected row, the bar shows `(2 hidden by filter)`.

### 6. "Copy for Claude" output format

Selection plus button writes Markdown to clipboard:

```markdown
## Sessions for analysis (3 selected, last 24h)

| Workflow | Phase | Status | Model | Tokens | Cost | Duration | Started |
|---|---|---|---|---|---|---|---|
| onboarding | review | failed | sonnet-4.6 | 47.2k | $0.18 | 2m 14s | 2026-04-18 09:14:22 |
| onboarding | implement | completed | sonnet-4.6 | 89.1k | $0.42 | 8m 02s | 2026-04-18 09:09:18 |
| onboarding | plan | completed | opus-4.7 | 12.3k | $0.31 | 1m 47s | 2026-04-18 09:05:11 |

Fetch full details with:
- `syn session show 7b3a91e4-2c5f-4d8a-9b1e-3f6a8d2c5e7b`
- `syn session show 9c2f4d12-8e7a-4b3c-91d2-5e4f7a8b3c1d`
- `syn session show 4e8f1a37-6c2b-4d5e-83a1-7f9c2b4e8d1a`
```

This is immediately useful pasted into Claude Code with no editing. Variants (table only, IDs only, with prompt skeleton) are reachable from a small dropdown next to the primary button.

### 7. Live updates (SSE)

A single shared `useActivityStream` hook owns one `EventSource('/sse/activity')` per browser tab, multiplexed across all consumers. Both `SessionList` and `ExecutionList` subscribe and patch their row sets in place.

**Backend change required:** add `broadcast_global("SessionStarted" | "SessionCompleted", payload)` calls alongside the existing per-execution broadcasts. Today the global activity channel only carries `git_commit` (`webhooks/push_events.py:57`); session and execution lifecycle events are only on the per-execution channel. Event names are PascalCase to match the domain event class names emitted by aggregates.

> **Note:** A `SessionUpdated` token-tick event does not exist today. The phase-1 implementation broadcasts only `SessionStarted` and `SessionCompleted`. Live token / cost counters during a running session are deferred until either a `SessionUpdated` event is added to the domain or an existing per-execution event is repurposed for the global activity feed.

**Polling remains as a fallback** triggered when `EventSource` errors out. The 5s interval on `useExecutionList` becomes the fallback path, not the primary path.

**Throttling (future, when `SessionUpdated` lands):** token / cost tick events for running sessions will be throttled server-side to one event per session per second. The terminal `SessionCompleted` is never throttled. Phase 1 has no throttling because only start / complete fire (~2 broadcasts per session).

### 8. Row click semantics

Row click toggles selection. Workflow name is a real link that navigates to detail. Chevron at the right edge expands an inline detail panel without navigating. This is the Linear / Notion pattern; it makes the analyse flow primary and keeps navigation accessible.

## Scalability Trade-offs

The design has an explicit ceiling. Recording it so we know when to revisit.

### Connection fan-out (SSE)

`/sse/activity` broadcasts every session lifecycle event to every subscriber. With N concurrent sessions and M concurrent dashboard tabs, fan-out is `O(N x M)` per event. At 1000 concurrent operators each watching the same global feed, a single session update is 1000 queue puts. Each subscriber queue is an `asyncio.Queue` (~10kB resident); 1000 connections is ~10MB of queue memory plus connection overhead. **This is fine for self-host and low-tens of operators. It is not fine for a multi-tenant SaaS deployment.**

Mitigations available when we need them:

- **Per-org channels.** Replace the single `_activity_` channel with `_activity_<org_id>` and require an authz check on subscribe. Reduces fan-out to per-tenant.
- **Filter at edge.** Send all events to all subscribers but tag with org / workflow; client discards irrelevant. Cheaper to broadcast, more bandwidth used.
- **Redis pub/sub backplane.** Today `RealTimeProjection._queues` is per-API-process. Horizontal scaling of `syn-api` (multiple replicas behind a load balancer) breaks broadcast unless events go through a shared bus. Redis pub/sub is the natural extension; out of scope here but should not be designed against.

### Update frequency throttling

Token-tick events for running sessions could fire on every Claude CLI chunk. Without throttling, a single chatty session can dominate the broadcast bus. When `SessionUpdated` is added in a later phase, we will throttle it to **1 event per session per second** server-side; terminal events bypass the throttle. Trade-off: the dashboard's live token counter for a running session can lag by up to 1s. Acceptable; this is a monitor, not a stopwatch.

### Client rendering at high row counts

A 1000-row dense table with 8 columns, sortable, with 60fps shimmer animations, will choke React's reconciler. The default 24h time window keeps row counts bounded in normal use (typical operator: < 200 sessions / 24h). Mitigations available:

- **Virtualise** (`@tanstack/react-virtual` or similar) when row count exceeds 200. Out of scope for v1; add when an operator hits the wall.
- **Debounce live patches** to max one visual update per row per 500ms. Already part of the design.
- **Server-side pagination.** Already supported by the API; the page hook switches to paged mode when "Show all" is clicked and result set exceeds a threshold.

### Selection size cap

Multi-select state is in-browser; arbitrarily large in memory. The "Copy for Claude" output, however, has a Claude Code context budget. We cap the visible selection at **100 rows** with a clear warning when the limit is hit. Below 100, the Markdown table fits comfortably in a single Claude Code prompt.

### Filter / sort cost

Client-side filter and sort is `O(N)` per interaction. Acceptable up to ~5000 rows. Beyond that, the page hook pushes filter and sort into the API query (the API already accepts `status` and `workflow_id`; sort is a small additional field). The threshold is internal to the hook; no UI change required.

### Where this design will need revisiting

| Trigger | Likely change |
|---|---|
| Multi-tenant SaaS deployment | Per-org SSE channels, authz on subscribe |
| Horizontal `syn-api` scale-out | Redis pub/sub broadcast backplane |
| Operator with >1000 sessions / 24h | Table virtualisation, server-side sort |
| Selection > 100 with copy-out demand | Server-side "copy bundle" endpoint that returns the Markdown directly |

## Open Questions

These are intentionally not decided in this ADR; they will be settled before or during phase 1 implementation:

1. **Row click semantics.** Confirmed direction is selection-toggle (Linear style). Revisit if user testing shows confusion.
2. **Time window default.** Proposed: "Last 24h" with prominent "Show all" link. Alternative: default "All" and let the user narrow. We will ship 24h and revisit based on usage.
3. **Inline expand-row depth.** What goes in the expanded panel? Proposed: token breakdown, model, workspace info, last 5 operations. To be prototyped in phase 1.
4. **`cli_version` API exposure.** The data exists in `RecordingMetadata.cli_version` (`packages/syn-adapters/.../recording/adapter.py:215`) but is not surfaced through the API. Tracked separately; the column toggle entry exists in the UI from day one but reads as "n/a" until the API change lands.
5. **Color stripe weight.** Stripe is more peripheral-vision-friendly; risk is visual heaviness on completed runs. We will start with a thin (3px) muted stripe and tune.
6. **Selection persistence across page reload.** Out of scope for v1. Adds complexity (URL state or localStorage) for a marginal win.

## Consequences

### Positive

- **One mental model for two pages.** Sessions and Executions look and behave the same way; learning one teaches the other.
- **Live by default.** Dashboard becomes a real monitor; no manual refresh.
- **Analysis flow is first-class.** Multi-select + Copy for Claude turns ad-hoc cost / failure investigation into a 3-click operation.
- **No new dependencies.** SSE infrastructure (ADR-049) is reused. `ResourceTable` is built on existing primitives.
- **Backend change is small and additive.** Three `broadcast_global` calls; no schema change, no new endpoints.

### Negative

- **Single shared SSE channel does not scale to multi-tenant SaaS** without per-org partitioning. Mitigation path documented above.
- **Client-side sort and filter has a row-count ceiling** (~5000 in practice). Mitigation path documented above.
- **`ResourceTable` is a new abstraction** to maintain. Mitigated by being one component used by exactly two pages on day one; if it ever grows a third consumer, the abstraction has earned its keep.
- **Two pages migrating in one PR** is a larger change than incremental updates. Mitigated by phasing inside the PR: phase 1 ships sessions and the shared primitive; phase 2 migrates executions on top of the now-validated primitive.

## Implementation

Phased inside a single PR.

### Phase 1: Sessions experiment + shared primitive

**Backend:**
- `apps/syn-api/src/syn_api/services/session_broadcast.py` (or extension to existing observability pipeline) — adds `broadcast_global` for session lifecycle events with throttling.

**Frontend:**
- `apps/syn-dashboard-ui/src/hooks/useActivityStream.ts` — single shared `EventSource` per tab.
- `apps/syn-dashboard-ui/src/components/ResourceTable/` — directory with the shared table primitive (table, header, row, expand panel, action bar, column toggle).
- `apps/syn-dashboard-ui/src/components/ResourceTable/copyForClaude.ts` — clipboard formatter.
- `apps/syn-dashboard-ui/src/hooks/useSessionList.ts` — replaced with SSE-driven version.
- `apps/syn-dashboard-ui/src/pages/SessionList.tsx` — rewritten on top of `ResourceTable`.

### Phase 2: Executions migration

- `apps/syn-dashboard-ui/src/hooks/useExecutionList.ts` — switch from polling-primary to SSE-primary with polling fallback.
- `apps/syn-dashboard-ui/src/pages/ExecutionList.tsx` — rewritten on top of `ResourceTable` with executions column config.

### Backlink convention

Every file listed above gets a top-of-file comment linking back to this ADR. Convention:

**TypeScript / TSX:**

```typescript
/**
 * ResourceTable: shared table primitive for live observability lists.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */
```

**Python:**

```python
"""Session lifecycle SSE broadcast.

See: docs/adrs/ADR-064-observability-monitor-ui.md
"""
```

The backlink lives below any existing module docstring, not in place of it. Files that change but are not "implementing" this ADR (e.g., `types/index.ts` getting a new field) do not need the backlink.

## References

- ADR-049: Server-Sent Events (SSE) for Real-Time Execution Streams (transport this builds on)
- ADR-044: CLI-First, Agent-Native Interface Design (philosophy: dashboard is a view, CLI is canonical)
- ADR-015: Agent Session Observability Architecture (data being visualised)
- ADR-039: Context Window and Cost Tracking (cost / token data being displayed)
- Linear's selection-mode interaction pattern (multi-select bottom action bar)
- Vercel deployments page (status-coded rows, live updates, expand for detail)
