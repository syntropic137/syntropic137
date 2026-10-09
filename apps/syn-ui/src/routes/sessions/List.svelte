<!--
  Sessions (boards: Sessions, PhoneSessions). Hero with the status split,
  then search, status chips with server counts and the time window, then
  one row per session: the phase leads (delegated children marked), the
  workflow and execution, agent and observed model, tokens, cost, duration
  and age. Rows have a fixed height so only the ones near the viewport render
  (windowRange); Pagination moves through the server's pages.
-->
<script lang="ts">
  import { formatInteger, formatRelativeTime } from '@syn137/skyline-core/format'
  import { agentKind, sessionListRow, sessionsForAgent, sessionsLede, sessionsLedeShort, windowRange } from '@syn137/skyline-core/screens/sessions'
  import { DEFAULT_LIST_WINDOW, TIME_WINDOWS, outcomeTotals, parseTimeWindow, timeWindowParam, timeWindowStart } from '@syn137/skyline-core/screens/executions'
  import { MAX_PAGE_SIZE, listSessions } from '@syn137/syn-ui-data'
  import { Button, Callout, EmptyState, Input, Pagination, Skeleton, Tag, ToggleGroup } from '@syn137/skyline-svelte-v5'
  import { CopyButton, ObjectIcon, StatusBadge } from '@syn137/skyline-svelte-v5/patterns'
  import { isRunEvent, isSessionEvent } from '@syn137/syn-ui-data/live'
  import { resource } from '../../lib/load.svelte'
  import { href, router } from '../../lib/router'
  import type { PageProps } from '../../lib/routes'

  let { params: _params }: PageProps = $props()

  // Owner tweak (Oct 8 2026): the last 24h, 100 rows a page. All stays one click away.
  const PAGE_SIZE = MAX_PAGE_SIZE
  const STATUSES = ['running', 'completed', 'failed', 'cancelled'] as const
  const LABEL: Record<string, string> = { running: 'Running', completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled' }

  const q = $derived(router.query.get('q') ?? '')
  const status = $derived(router.query.get('status') ?? 'all')
  const page = $derived(Math.max(1, Number(router.query.get('page')) || 1))
  const workflowId = $derived(router.query.get('workflow_id') ?? undefined)
  const timeWindow = $derived(parseTimeWindow(router.query.get('window'), DEFAULT_LIST_WINDOW))

  const list = resource(
    (signal) =>
      listSessions(
        { page, page_size: PAGE_SIZE, started_after: timeWindowStart(timeWindow, Date.now()), q: q || undefined, statuses: status === 'all' ? undefined : [status], ...(workflowId ? { workflow_id: workflowId } : {}) },
        signal,
      ),
    { live: (type) => isSessionEvent(type) || isRunEvent(type) },
  )

  let search = $state('')
  $effect(() => {
    search = q
  })
  let timer: ReturnType<typeof setTimeout> | undefined
  const onSearch = (value: string) => {
    clearTimeout(timer)
    timer = setTimeout(() => router.setQuery({ q: value, page: null }), 250)
  }

  const counts = $derived((list.data?.status_counts ?? {}) as Record<string, number>)
  const allCount = $derived(Object.values(counts).reduce((a, b) => a + b, 0))
  const totals = $derived(outcomeTotals(counts))
  const outcomeLabel = $derived(`${totals.completed} completed, ${totals.failed} failed, ${totals.cancelled} cancelled`)
  const chips = $derived([
    { value: 'all', label: 'All', count: allCount },
    ...STATUSES.map((s) => ({ value: s, label: LABEL[s]!, count: counts[s] ?? 0 })),
  ])
  let chipValue = $state<string[]>(['all'])
  $effect(() => {
    chipValue = [status]
  })
  $effect(() => {
    const v = chipValue[0] ?? 'all'
    if (v !== status) router.setQuery({ status: v === 'all' ? null : v, page: null })
  })

  const rows = $derived(list.data?.sessions ?? [])
  const now = Date.now()

  // Windowing: rows are a fixed height per breakpoint; measure the first one.
  let listEl = $state<HTMLElement | null>(null)
  let rowHeight = $state(72)
  let offset = $state(0)
  let viewport = $state(typeof window === 'undefined' ? 800 : window.innerHeight)
  $effect(() => {
    const onScroll = () => {
      if (!listEl) return
      offset = -listEl.getBoundingClientRect().top
      viewport = window.innerHeight
    }
    onScroll()
    addEventListener('scroll', onScroll, { passive: true })
    addEventListener('resize', onScroll, { passive: true })
    return () => {
      removeEventListener('scroll', onScroll)
      removeEventListener('resize', onScroll)
    }
  })
  const range = $derived(windowRange({ offset, viewport, rowHeight, count: rows.length }))
  const visible = $derived(rows.slice(range.start, range.end))
  const measure = (node: HTMLElement) => {
    const h = node.offsetHeight
    if (h > 0 && Math.abs(h - rowHeight) > 0.5) rowHeight = h
  }

  const filtered = $derived(q !== '' || status !== 'all' || !!workflowId || timeWindow !== DEFAULT_LIST_WINDOW)
  const clear = () => router.setQuery({ q: null, status: null, page: null, workflow_id: null, window: null })
</script>

<div class="sky-sessions">
  <section class="sky-sessions__hero" aria-label="Sessions" data-total={list.data?.total}>
    <div class="sky-sessions__intro">
      <ObjectIcon kind="session" size={84} />
      <div class="sky-sessions__titles">
        <h1>Sessions</h1>
        {#if list.data}
          <p class="sky-sessions__lede sky-sessions__lede--long">{sessionsLede(totals)}</p>
          <p class="sky-sessions__lede sky-sessions__lede--short">{sessionsLedeShort(totals)}</p>
        {:else}
          <Skeleton variant="text" width="16rem" />
        {/if}
      </div>
    </div>
    <div class="sky-sessions__outcomes">
      <div class="sky-sessions__split" role="img" aria-label={outcomeLabel}>
        {#if totals.completed + totals.failed + totals.cancelled > 0}
          <span data-tone="completed" style:flex-grow={totals.completed}></span>
          <span data-tone="failed" style:flex-grow={totals.failed}></span>
          <span data-tone="cancelled" style:flex-grow={totals.cancelled}></span>
        {:else}
          <span data-tone="empty" style:flex-grow={1}></span>
        {/if}
      </div>
      <div class="sky-sessions__figures">
        {#each [['completed', totals.completed], ['failed', totals.failed], ['cancelled', totals.cancelled]] as const as [tone, n] (tone)}
          <div class="sky-sessions__figure">
            <span class="sky-sessions__figure-value">{list.data ? formatInteger(n) : '—'}</span>
            <span class="sky-sessions__figure-label"><span class="sky-sessions__swatch" data-tone={tone}></span>{tone}</span>
          </div>
        {/each}
      </div>
    </div>
  </section>

  <div class="sky-sessions__filters">
    <Input type="search" aria-label="Search sessions" placeholder="Phase, workflow, model or ID" bind:value={search} oninput={(e) => onSearch(e.currentTarget.value)} />
    <ToggleGroup class="sky-sessions__chips" type="single" variant="chips" aria-label="Filter by status" bind:value={chipValue} items={chips} />
    <ToggleGroup
      class="sky-sessions__window"
      type="single"
      variant="segmented"
      mono
      aria-label="Time window"
      items={TIME_WINDOWS.map((w) => ({ value: w.value, label: w.label }))}
      value={[timeWindow]}
      onValueChange={(v) => router.setQuery({ window: timeWindowParam(v[0], DEFAULT_LIST_WINDOW), page: null })}
    />
    {#if rows.length}
      <CopyButton variant="label" text={() => sessionsForAgent(rows)} label="Copy for agent" copiedLabel="Copied for agent" />
    {/if}
  </div>

  {#if list.error && !list.data}
    <Callout tone="danger" title="Couldn't load sessions." role="alert">
      {list.error instanceof Error ? list.error.message : 'Unknown error'}
      {#snippet action()}<Button size="sm" onclick={() => list.refresh()}>Retry</Button>{/snippet}
    </Callout>
  {:else if !list.data}
    <div class="sky-sessions__skeleton">
      <Skeleton label="Loading sessions" variant="block" height="4.5rem" />
      {#each { length: 6 } as _, i (i)}<Skeleton variant="block" height="4.5rem" />{/each}
    </div>
  {:else if rows.length === 0}
    <EmptyState
      title={filtered ? 'No sessions match' : timeWindow !== 'all' ? 'No sessions in the last 24 hours' : 'No sessions yet'}
      description={filtered ? 'Try another search, status or time window, or clear the filters.' : timeWindow !== 'all' ? 'Older sessions are under All.' : 'Sessions appear here when a workflow runs.'}
    >
      {#snippet action()}
        {#if filtered}<Button onclick={clear}>Clear filters</Button>{:else if timeWindow !== 'all'}<Button onclick={() => router.setQuery({ window: 'all', page: null })}>Show all</Button>{:else}<Button href={href('/workflows')}>Run a workflow</Button>{/if}
      {/snippet}
    </EmptyState>
  {:else}
    {#if list.error}
      <Callout tone="warning" title="Showing the last results.">The list could not refresh. <Button size="sm" variant="ghost" onclick={() => list.refresh()}>Retry</Button></Callout>
    {/if}
    <section class="sky-sessions__table" aria-label="Session list">
      <div class="sky-sessions__colhead" aria-hidden="true">
        <span></span>
        <span>Session</span>
        <span>Execution</span>
        <span>Agent · model</span>
        <span class="sky-sessions__right">Tokens</span>
        <span class="sky-sessions__right">Cost</span>
        <span class="sky-sessions__right">Took</span>
        <span class="sky-sessions__right sky-sessions__sorted">Started ↓</span>
      </div>
      <ol class="sky-sessions__list" bind:this={listEl} aria-label="Sessions" aria-busy={list.loading} style:padding-top="{range.padTop}px" style:padding-bottom="{range.padBottom}px">
        {#each visible as s, i (s.id)}
          {@const r = sessionListRow(s)}
          <li class="sky-sessions__item" data-sky-row aria-setsize={rows.length} aria-posinset={range.start + i + 1}>
            <a class="sky-sessions__row" href={href(`/sessions/${encodeURIComponent(s.id)}`)} data-delegated={r.delegated || undefined} use:measure>
              <StatusBadge status={s.status} shape="square" />
              <span class="sky-sessions__title">{#if r.delegated}<span class="sky-sessions__child" aria-hidden="true">↳ </span>{/if}{r.title}</span>
              <span class="sky-sessions__workflow">{r.workflow}</span>
              <span class="sky-sessions__exec">{r.execution}</span>
              <span class="sky-sessions__num" data-col="tokens"><span class="sky-visually-hidden">Tokens </span>{s.total_tokens_display}<span class="sky-sessions__unit">{' tok'}</span></span>
              <span class="sky-sessions__num" data-col="cost"><span class="sky-visually-hidden">Cost </span>{s.total_cost_display}{#if s.unpriced_observation_count}+{/if}</span>
              <span class="sky-sessions__foot">
                <span class="sky-sessions__agent"><Tag variant="agent" agent={agentKind(s.agent_provider)} title={s.requested_model ? `${r.agent} (requested: ${s.requested_model})` : r.agent}>{#if r.provider}<span class="sky-sessions__provider">{r.provider} · </span>{/if}{r.model}</Tag></span>
                <span class="sky-sessions__sub">{r.sub}</span>
                <span class="sky-sessions__num" data-col="duration"><span class="sky-visually-hidden">Duration </span>{s.duration_display}</span>
                <span class="sky-sessions__num" data-col="when">{formatRelativeTime(s.started_at, { now })}</span>
              </span>
            </a>
          </li>
        {/each}
      </ol>
    </section>
    {#if list.data.total > PAGE_SIZE}
      <Pagination
        page={page}
        pageCount={Math.ceil(list.data.total / PAGE_SIZE)}
        summary={`Showing ${formatInteger(rows.length)} of ${formatInteger(list.data.total)} sessions`}
        onPageChange={(p: number) => router.setQuery({ page: p === 1 ? null : String(p) }, { push: true })}
      />
    {:else}
      <p class="sky-sessions__foot">Showing {formatInteger(rows.length)} of {formatInteger(list.data.total)} sessions{#if list.data.excluded_undated} · {list.data.excluded_undated} undated not shown{/if}</p>
    {/if}
  {/if}
</div>

<style>
  .sky-sessions {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
  }
  .sky-sessions__hero {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-2xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background:
      radial-gradient(50% 130% at 100% 0%, var(--sky-color-accent-soft), transparent 70%),
      var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-sessions__intro {
    display: flex;
    align-items: center;
    gap: var(--ds-space-4);
    min-width: 0;
  }
  .sky-sessions__intro :global(.sky-object-icon) {
    flex-shrink: 0;
    width: var(--sky-size-object-icon-sm);
    height: var(--sky-size-object-icon-sm);
  }
  .sky-sessions__provider {
    display: none;
  }
  .sky-sessions__titles {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  h1 {
    margin: 0;
    font-size: var(--sky-text-page);
    line-height: 1.05;
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.035em;
  }
  .sky-sessions__lede {
    margin: 0;
    color: var(--ds-color-text-muted);
  }
  .sky-sessions__lede--long {
    display: none;
  }
  .sky-sessions__outcomes {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3-5);
    min-width: 0;
  }
  .sky-sessions__split {
    display: flex;
    gap: 3px;
    height: 12px;
  }
  .sky-sessions__split > span {
    flex-basis: 0;
    border-radius: 4px;
  }
  [data-tone='completed'] {
    background: var(--sky-status-completed);
  }
  [data-tone='failed'] {
    background: var(--sky-status-failed);
  }
  [data-tone='cancelled'] {
    background: var(--sky-status-cancelled);
  }
  [data-tone='empty'] {
    background: var(--sky-color-track);
  }
  .sky-sessions__figures {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--ds-space-4);
  }
  .sky-sessions__figure {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .sky-sessions__figure-value {
    font-size: var(--sky-text-figure);
    line-height: 1.1;
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
  }
  .sky-sessions__figure-label {
    display: flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-sessions__swatch {
    width: 8px;
    height: 8px;
    border-radius: 2px;
  }
  .sky-sessions__filters {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-sessions__filters > :global(*) {
    min-width: 0;
  }
  .sky-sessions__filters > :global(:last-child) {
    align-self: flex-start;
  }
  .sky-sessions__skeleton {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
  }
  .sky-sessions__table {
    min-width: 0;
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-sessions__colhead {
    display: none;
  }
  .sky-sessions__list {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-sessions__item + .sky-sessions__item {
    border-top: var(--ds-border-width) solid var(--sky-color-divider);
  }
  /* Phone board: phase and workflow left, cost over tokens right, then model, id and timing. */
  .sky-sessions__row {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    grid-template-areas:
      'badge title cost'
      'badge workflow tokens'
      'foot foot foot';
    align-items: center;
    column-gap: var(--ds-space-3);
    row-gap: var(--ds-space-1);
    box-sizing: border-box;
    height: 7.25rem;
    padding: var(--ds-space-3) var(--ds-space-4);
    color: var(--ds-color-fg);
    text-decoration: none;
  }
  .sky-sessions__row > :global(:first-child) {
    grid-area: badge;
    align-self: start;
  }
  .sky-sessions__row:hover {
    background: var(--sky-color-control-hover);
  }
  .sky-sessions__row:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: calc(-1 * var(--sky-focus-ring-width));
    border-radius: var(--sky-radius-row);
  }
  .sky-sessions__title,
  .sky-sessions__workflow,
  .sky-sessions__exec,
  .sky-sessions__sub {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-sessions__title {
    grid-area: title;
    font-size: var(--sky-text-body);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-sessions__child {
    color: var(--ds-color-text-subtle);
    font-weight: var(--ds-font-weight-regular);
  }
  .sky-sessions__workflow {
    grid-area: workflow;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-sessions__exec {
    display: none;
  }
  .sky-sessions__sub,
  .sky-sessions__exec {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-sessions__foot {
    grid-area: foot;
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    min-width: 0;
    margin-top: var(--ds-space-1-5);
  }
  .sky-sessions__agent {
    flex: 0 0 auto;
    max-width: 65%;
    min-width: 0;
    overflow: hidden;
  }
  .sky-sessions__foot .sky-sessions__sub {
    flex: 1 1 0;
  }
  .sky-sessions__num {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    text-align: right;
  }
  .sky-sessions__num[data-col='cost'] {
    grid-area: cost;
    font-size: var(--sky-text-data);
    color: var(--ds-color-fg);
  }
  .sky-sessions__num[data-col='tokens'] {
    grid-area: tokens;
    color: var(--ds-color-text-subtle);
  }
  .sky-sessions__num[data-col='when'] {
    margin-left: auto;
    color: var(--ds-color-text-subtle);
  }
  .sky-sessions__foot .sky-sessions__num {
    flex-shrink: 0;
  }
  .sky-sessions__row[data-delegated] .sky-sessions__title,
  .sky-sessions__row[data-delegated] .sky-sessions__workflow {
    padding-inline-start: var(--ds-space-3);
  }
  .sky-sessions__right {
    text-align: right;
  }
  .sky-sessions__sorted {
    color: var(--ds-color-fg);
  }
  .sky-sessions__unit {
    color: var(--ds-color-text-subtle);
  }

  @media (min-width: 48rem) {
    .sky-sessions {
      gap: var(--ds-space-6);
    }
    .sky-sessions__hero {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--ds-space-7) var(--ds-space-12);
      padding: var(--ds-space-8) var(--ds-space-9);
    }
    .sky-sessions__intro {
      gap: var(--ds-space-6);
    }
    .sky-sessions__intro :global(.sky-object-icon) {
      width: var(--sky-size-object-icon-lg);
      height: var(--sky-size-object-icon-lg);
    }
    .sky-sessions__titles {
      max-width: 36rem;
    }
    .sky-sessions__lede--long {
      display: block;
    }
    .sky-sessions__lede--short {
      display: none;
    }
    .sky-sessions__outcomes {
      width: 22.5rem;
      max-width: 100%;
    }
    .sky-sessions__filters {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--ds-space-3) var(--ds-space-4);
    }
    .sky-sessions__filters > :global(.sky-sessions__chips) {
      order: -1;
      flex: 1 1 auto;
    }
    .sky-sessions__filters > :global(:first-child) {
      flex: 0 1 18rem;
    }
    .sky-sessions__filters > :global(:last-child) {
      align-self: auto;
    }
    .sky-sessions__table {
      padding: var(--ds-space-2-5);
      border-radius: var(--sky-radius-card-lg);
    }
    .sky-sessions__colhead,
    .sky-sessions__row {
      display: grid;
      grid-template-columns: var(--sky-size-control-sm) minmax(10rem, 1.3fr) minmax(9rem, 1fr) minmax(0, 15rem) 4.5rem 4.5rem 4.5rem 4.5rem;
      column-gap: var(--ds-space-4);
    }
    .sky-sessions__colhead {
      align-items: center;
      height: 36px;
      padding: 0 var(--ds-space-3);
      font-family: var(--ds-font-mono);
      font-size: var(--sky-text-label);
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--ds-color-text-subtle);
    }
    .sky-sessions__row {
      grid-template-areas:
        'badge title workflow agent tokens cost took when'
        'badge sub exec agent tokens cost took when';
      row-gap: 2px;
      height: 4.25rem;
      padding: 0 var(--ds-space-3);
    }
    .sky-sessions__row > :global(:first-child) {
      align-self: center;
    }
    .sky-sessions__foot {
      display: contents;
    }
    .sky-sessions__workflow {
      align-self: end;
      color: var(--ds-color-fg);
    }
    .sky-sessions__title {
      align-self: end;
    }
    .sky-sessions__sub {
      grid-area: sub;
      align-self: start;
    }
    .sky-sessions__exec {
      display: block;
      grid-area: exec;
      align-self: start;
    }
    .sky-sessions__agent {
      grid-area: agent;
      max-width: 100%;
    }
    .sky-sessions__num {
      font-size: var(--sky-text-data);
    }
    .sky-sessions__num[data-col='tokens'] {
      color: var(--ds-color-fg);
    }
    .sky-sessions__num[data-col='duration'] {
      grid-area: took;
    }
    .sky-sessions__num[data-col='when'] {
      grid-area: when;
      margin-left: 0;
    }
    .sky-sessions__unit {
      display: none;
    }
    .sky-sessions__provider {
      display: inline;
    }
    .sky-sessions__row[data-delegated] .sky-sessions__sub {
      padding-inline-start: var(--ds-space-3);
    }
  }
</style>
