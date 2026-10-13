<!--
  Session detail (Session · PhoneSession boards). Header with status, agent
  and figures; the Usage Meter by model; then the Operation Timeline with
  filter chips, Expand all and Copy all. Long timelines render in chunks as
  the reader scrolls (revealCount), so a 600-operation session stays light.
  Operations read newest first; while the session runs they refresh on the
  execution's own stream (and a 3 s poll, since the API forwards no
  per-operation frame yet). Rows that arrive while the reader is scrolled
  down keep the viewport still and show as "N new" (feedback 18ec6964).
-->
<script lang="ts">
  import { untrack } from 'svelte'
  import { formatInteger, formatTokens } from '@syn137/skyline-core/format'
  import {
    agentLabel,
    costByModelRows,
    countToolCalls,
    filterOperations,
    LIVE_OPS_INITIAL,
    liveOps,
    newestFirst,
    operationChips,
    operationsSummary,
    revealCount,
    sessionCost,
    sessionCrumbs,
    sessionDurationText,
    sessionOperations,
    sessionPollMs,
    sessionTokens,
    transcriptAvailable,
    unseenLabel,
  } from '@syn137/skyline-core/screens/sessions'
  import { operationsToText } from '@syn137/skyline-core/patterns'
  import { ApiError, getSession } from '@syn137/syn-ui-data'
  import { Button, Callout, Card, EmptyState, Skeleton, ToggleGroup } from '@syn137/skyline-svelte-v5'
  import { CopyButton, HarnessChip, OperationTimeline, PageHeader, UsageMeter } from '@syn137/skyline-svelte-v5/patterns'
  import { isRunEvent, isSessionEvent } from '@syn137/syn-ui-data/live'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import { href } from '../../lib/router'
  import type { PageProps } from '../../lib/routes'
  import Transcript from './Transcript.svelte'

  let { params }: PageProps = $props()

  const session = resource((signal) => getSession(params.sessionId ?? '', signal), {
    live: (type) => isSessionEvent(type) || isRunEvent(type),
  })

  const s = $derived(session.data)
  const rows = $derived(s ? newestFirst(sessionOperations(s.operations)) : [])
  const chips = $derived(operationChips(rows))
  let filter = $state<string[]>(['all'])
  const current = $derived(chips.some((c) => c.value === filter[0]) ? (filter[0] ?? 'all') : 'all')
  const shown = $derived(filterOperations(rows, current))
  let expanded = $state(false)
  let transcriptOpen = $state(false)

  // Chunked rendering: show the first chunk, add one each time the sentinel nears the viewport.
  const CHUNK = 40
  let limit = $state(CHUNK)
  $effect(() => {
    void current
    limit = CHUNK
  })
  const visible = $derived(shown.slice(0, limit))
  let sentinel = $state<HTMLElement | null>(null)
  $effect(() => {
    const el = sentinel
    if (!el || typeof IntersectionObserver === 'undefined') return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) limit = revealCount(limit, shown.length, CHUNK)
      },
      { rootMargin: '800px 0px' },
    )
    io.observe(el)
    return () => io.disconnect()
  })

  // Live: the execution's stream invalidates this session's cached read on its frames; a running session also polls.
  const execId = $derived(s?.execution_id ?? null)
  const pollMs = $derived(sessionPollMs(s?.status))
  $effect(() => {
    const ex = execId
    if (!ex || pollMs === null) return
    let stop: (() => void) | null = null
    let gone = false
    void import('@syn137/syn-ui-data/invalidate').then((m) => {
      if (!gone) stop = m.connectExecutionInvalidation(ex)
    })
    return () => {
      gone = true
      stop?.()
    }
  })
  $effect(() => {
    const ms = pollMs
    if (ms === null) return
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') session.refresh()
    }, ms)
    return () => clearInterval(timer)
  })

  // New rows prepend. At the top they just appear; scrolled down, the row the reader is on stays put and "N new" counts them.
  let listEl = $state<HTMLElement | null>(null)
  let ops = $state(LIVE_OPS_INITIAL)
  let anchor: { id: string; top: number } | null = null
  const listAtTop = () => !listEl || listEl.getBoundingClientRect().top >= 0
  function firstVisibleRow(): { id: string; top: number } | null {
    for (const el of listEl?.querySelectorAll<HTMLElement>('[data-op-id]') ?? []) {
      const r = el.getBoundingClientRect()
      if (r.bottom > 0) return { id: el.dataset.opId ?? '', top: r.top }
    }
    return null
  }
  $effect.pre(() => {
    if (!s) return
    const ids = rows.map((r) => r.id)
    untrack(() => {
      const atTop = listAtTop()
      const next = liveOps(ops, { type: 'rows', ids, atTop })
      if (next.added > 0 && !atTop) {
        anchor = firstVisibleRow()
        limit += next.added
      }
      ops = next
    })
  })
  $effect(() => {
    void visible
    const a = anchor
    anchor = null
    if (!a || !listEl) return
    const el = listEl.querySelector<HTMLElement>(`[data-op-id="${CSS.escape(a.id)}"]`)
    if (el) window.scrollBy(0, el.getBoundingClientRect().top - a.top)
  })
  $effect(() => {
    const onScroll = () => {
      if (ops.unseen > 0 && listAtTop()) ops = liveOps(ops, { type: 'seen' })
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  })
  function showNew() {
    ops = liveOps(ops, { type: 'seen' })
    document.getElementById('operations-timeline')?.scrollIntoView({ block: 'start' })
  }

  const cost = $derived(s ? sessionCost(s.total_cost_usd, s.unpriced_observation_count) : null)
  const figures = $derived(
    s
      ? [
          { label: 'Duration', value: sessionDurationText(s) },
          { label: 'Cost', value: cost?.display ?? '—' },
          { label: 'Tool calls', value: formatInteger(countToolCalls(rows)) },
          { label: 'Tokens', value: formatTokens(s.total_tokens, { case: 'upper' }) },
        ]
      : [],
  )

  $effect(() => {
    if (!s) return
    setPage({ title: `${s.phase_display ?? 'Session'} · ${s.workflow_name ?? 'Session'}`, crumbs: sessionCrumbs(s) })
  })

  const notFound = $derived(session.error instanceof ApiError && session.error.status === 404)
  const errorText = $derived(session.error instanceof Error ? session.error.message : 'The session could not be loaded.')
  const inventoryHref = $derived(
    s?.execution_id
      ? `/executions/${encodeURIComponent(s.execution_id)}${s.phase_id ? `?inventory_phase=${encodeURIComponent(s.phase_id)}` : ''}#session-inventory`
      : null,
  )
</script>

<div class="sky-session">
  {#if session.error && !s}
    {#if notFound}
      <EmptyState title="Session not found" description={`No session has the ID ${params.sessionId}. It may belong to a deleted execution.`}>
        {#snippet action()}<Button href={href('/sessions')}>All sessions</Button>{/snippet}
      </EmptyState>
    {:else}
      <Callout tone="danger" title="Couldn't load this session." role="alert">
        {errorText}
        {#snippet action()}<Button size="sm" onclick={() => session.refresh()}>Retry</Button>{/snippet}
      </Callout>
    {/if}
  {:else if !s}
    <div class="sky-session__loading" aria-busy="true">
      <Card><Skeleton lines={4} label="Loading session" /></Card>
      <Card><Skeleton variant="block" height="7rem" /></Card>
      <Card><Skeleton lines={6} /></Card>
    </div>
  {:else}
    <PageHeader kind="session" title={s.workflow_name ?? `Session ${s.id.slice(0, 8)}`} eyebrow={s.phase_display ?? s.phase_id ?? undefined} status={s.status} {figures}>
      {#snippet badges()}
        <HarnessChip provider={s.agent_provider ?? ''} label={agentLabel(s.agent_provider, s.agent_model_display, s.agent_model)} title={s.requested_model ? `Requested: ${s.requested_model}` : undefined} />
      {/snippet}
      {#snippet actions()}
        <Button
          variant="outline"
          disabled={!transcriptAvailable(s.status)}
          title={transcriptAvailable(s.status) ? undefined : 'The transcript is available once the session finishes'}
          onclick={() => (transcriptOpen = true)}
        >
          {#snippet icon()}
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 1.75h5l3 3v9.5H4zM9 1.75v3h3M6 8h4M6 10.75h4"></path></svg>
          {/snippet}
          View transcript
        </Button>
      {/snippet}
      <div class="sky-session__facts">
        <span class="sky-session__id">{s.id}</span>
        {#if inventoryHref}
          <a class="sky-session__link" href={href(inventoryHref)}>All sessions for this {s.phase_id ? 'phase' : 'run'} →</a>
        {/if}
      </div>
    </PageHeader>

    {#if s.error_message}
      <Callout tone="danger" title="The session failed.">{s.error_message}</Callout>
    {/if}

    <UsageMeter
      cost={cost?.display}
      tokens={sessionTokens(s)}
      costRows={costByModelRows(s.cost_by_model, s.agent_provider)}
      costBy="model"
      note={cost?.note ?? (Object.keys(s.cost_by_model ?? {}).length === 0 ? 'No model reported a price for this session.' : undefined)}
      rates={{
        ...(s.cache_read_rate_display ? { cacheRead: s.cache_read_rate_display } : {}),
        ...(s.cache_write_rate_display ? { cacheWrite: s.cache_write_rate_display } : {}),
      }}
    />

    <section class="sky-session__ops" aria-labelledby="sky-session-ops" id="operations-timeline">
      <header class="sky-session__ops-head">
        <div class="sky-session__ops-title">
          <h2 id="sky-session-ops">Operations</h2>
          <span class="sky-session__summary">{operationsSummary(rows, shown.length, s.operations.length, current)}</span>
        </div>
        {#if rows.length}
          <div class="sky-session__ops-tools">
            <ToggleGroup
              type="single"
              variant="chips"
              aria-label="Filter operations"
              bind:value={filter}
              items={chips.map((c) => ({ value: c.value, label: c.label, count: c.value === 'all' ? undefined : c.count }))}
            />
            <span class="sky-session__divider" aria-hidden="true"></span>
            <div class="sky-session__actions">
              <Button variant="ghost" size="sm" aria-pressed={expanded} onclick={() => (expanded = !expanded)}>{expanded ? 'Collapse all' : 'Expand all'}</Button>
              <CopyButton variant="label" text={() => operationsToText(shown)} label="Copy all" copiedLabel="Copied all" />
            </div>
          </div>
        {/if}
      </header>

      {#if rows.length === 0}
        <EmptyState bare level={3} title="No operations recorded yet" description={s.status === 'running' ? 'Tool calls appear here as the agent makes them.' : 'This session finished without recording a tool call.'} />
      {:else if shown.length === 0}
        <EmptyState bare level={3} title="Nothing matches this filter" description="Pick another chip, or show every operation.">
          {#snippet action()}<Button size="sm" onclick={() => (filter = ['all'])}>Show all</Button>{/snippet}
        </EmptyState>
      {:else}
        {#if ops.unseen > 0}
          <button type="button" class="sky-session__new" onclick={showNew}>
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 13V3M3.5 7.5 8 3l4.5 4.5"></path></svg>
            {unseenLabel(ops.unseen)}
          </button>
        {/if}
        <div class="sky-session__list" bind:this={listEl}>
          <OperationTimeline operations={visible} {expanded} aria-label="Operations, newest first" />
        </div>
        {#if visible.length < shown.length}
          <div class="sky-session__more" bind:this={sentinel}>
            <Button variant="ghost" size="sm" onclick={() => (limit = revealCount(limit, shown.length, CHUNK))}>
              Show more ({formatInteger(shown.length - visible.length)} left)
            </Button>
          </div>
        {/if}
      {/if}
    </section>

    {#if transcriptOpen}
      <Transcript sessionId={s.id} bind:open={transcriptOpen} />
    {/if}
  {/if}
</div>

<style>
  .sky-session {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    min-width: 0;
  }
  .sky-session__loading {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
  }
  .sky-session__facts {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2) var(--ds-space-4);
    min-width: 0;
  }
  .sky-session__id {
    min-width: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
    overflow-wrap: anywhere;
  }
  .sky-session__link {
    display: inline-flex;
    align-items: center;
    font-size: var(--sky-text-data);
    color: var(--ds-color-fg);
    text-decoration: underline;
    text-decoration-color: var(--sky-color-border-hover);
    text-underline-offset: 3px;
  }
  .sky-session__link:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-session__ops {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    min-width: 0;
    padding: var(--ds-space-4);
    border-radius: var(--sky-radius-card-lg);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-session__ops-head {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-session__ops-title {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--ds-space-1) var(--ds-space-3);
  }
  .sky-session__ops-title h2 {
    margin: 0;
    font-size: var(--ds-text-xl);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.015em;
  }
  .sky-session__summary {
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-session__ops-tools {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-session__divider {
    display: none;
  }
  .sky-session__actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2);
  }
  /* Phone board: View transcript spans the card under the figures. */
  .sky-session :global(.sky-page-header__actions > .sky-button) {
    width: 100%;
  }
  /* Scroll anchoring is ours (rows prepend above the reader); the browser's own would move it twice. */
  .sky-session__ops {
    overflow-anchor: none;
  }
  .sky-session__list {
    min-width: 0;
  }
  .sky-session__new {
    position: sticky;
    top: var(--ds-space-3);
    z-index: 2;
    align-self: center;
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    min-height: var(--sky-size-control-sm);
    padding: 0 var(--ds-space-3);
    border: var(--ds-border-width) solid var(--sky-color-accent-ring);
    border-radius: var(--ds-radius-full);
    background: var(--ds-color-surface-raised);
    box-shadow: var(--sky-shadow-overlay);
    color: var(--sky-color-accent-soft-fg);
    font: inherit;
    font-size: var(--ds-text-sm);
    cursor: pointer;
  }
  .sky-session__new:hover {
    border-color: var(--sky-color-border-hover);
  }
  .sky-session__new:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-session__new {
      min-height: var(--sky-size-touch);
    }
  }
  .sky-session__more {
    display: flex;
    justify-content: center;
  }

  @container (min-width: 44rem) {
    .sky-session :global(.sky-page-header__actions > .sky-button) {
      width: auto;
    }
  }

  @media (min-width: 48rem) {
    .sky-session {
      gap: var(--ds-space-7);
    }
    .sky-session__ops {
      padding: var(--ds-space-6);
    }
    .sky-session__ops-head {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
    }
    .sky-session__ops-tools {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: center;
    }
    .sky-session__divider {
      display: block;
      width: 1px;
      height: 18px;
      background: var(--sky-color-divider);
    }
  }
</style>
