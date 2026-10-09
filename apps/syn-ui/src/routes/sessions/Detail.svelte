<!--
  Session detail (Session · PhoneSession boards). Header with status, agent
  and figures; the Usage Meter by model; then the Operation Timeline with
  filter chips, Expand all and Copy all. Long timelines render in chunks as
  the reader scrolls (revealCount), so a 600-operation session stays light.
-->
<script lang="ts">
  import { formatDurationPrecise, formatInteger, formatTokens } from '@syn137/skyline-core/format'
  import {
    agentLabel,
    costByModelRows,
    countToolCalls,
    filterOperations,
    operationChips,
    operationsSummary,
    revealCount,
    sessionCost,
    sessionCrumbs,
    sessionOperations,
    sessionTokens,
    transcriptAvailable,
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
  const rows = $derived(s ? sessionOperations(s.operations) : [])
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

  const cost = $derived(s ? sessionCost(s.total_cost_usd, s.unpriced_observation_count) : null)
  const figures = $derived(
    s
      ? [
          { label: 'Duration', value: s.duration_seconds === null ? '—' : formatDurationPrecise(s.duration_seconds * 1000).replace(/\.0s$/, 's') },
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
        <HarnessChip provider={s.agent_provider ?? ''} label={agentLabel(s.agent_provider, s.agent_model_display, s.agent_model)} title={s.requested_model ? `Requested: ${s.requested_model}` : undefined} />
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
        <OperationTimeline operations={visible} {expanded} aria-label="Operations, oldest first" />
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
  .sky-session__more {
    display: flex;
    justify-content: center;
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
