<!--
  Sessions list (no board: drawn in the Executions list language). Title and
  count, search, status chips with server counts, then one row per session:
  status tile, workflow and phase, agent and repo, tokens, cost, duration and
  age. Rows have a fixed height so only the ones near the viewport render
  (windowRange); Pagination moves through the server's pages.
-->
<script lang="ts">
  import { formatInteger, formatRelativeTime } from '@syn137/skyline-core/format'
  import { sessionRowSub, sessionsForAgent, windowRange } from '@syn137/skyline-core/screens/sessions'
  import { listSessions } from '@syn137/syn-ui-data'
  import { Button, Callout, EmptyState, Input, Pagination, Skeleton, ToggleGroup } from '@syn137/skyline-svelte-v5'
  import { CopyButton, StatusBadge } from '@syn137/skyline-svelte-v5/patterns'
  import { resource } from '../../lib/load.svelte'
  import { href, router } from '../../lib/router'
  import type { PageProps } from '../../lib/routes'

  let { params: _params }: PageProps = $props()

  const PAGE_SIZE = 100
  const STATUSES = ['running', 'completed', 'failed', 'cancelled'] as const
  const LABEL: Record<string, string> = { running: 'Running', completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled' }

  const q = $derived(router.query.get('q') ?? '')
  const status = $derived(router.query.get('status') ?? 'all')
  const page = $derived(Math.max(1, Number(router.query.get('page')) || 1))
  const workflowId = $derived(router.query.get('workflow_id') ?? undefined)

  const list = resource(
    (signal) =>
      listSessions(
        { page, page_size: PAGE_SIZE, q: q || undefined, statuses: status === 'all' ? undefined : [status], ...(workflowId ? { workflow_id: workflowId } : {}) },
        signal,
      ),
    { live: (type) => type.startsWith('session') || type.startsWith('phase') },
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

  const filtered = $derived(q !== '' || status !== 'all' || !!workflowId)
  const clear = () => router.setQuery({ q: null, status: null, page: null, workflow_id: null })
</script>

<div class="sky-sessions">
  <header class="sky-sessions__head">
    <div class="sky-sessions__title">
      <h1>Sessions</h1>
      <p>Every agent session across workflows{#if list.data}<span class="sky-sessions__count"> · {formatInteger(list.data.total)}</span>{/if}</p>
    </div>
    {#if rows.length}
      <CopyButton variant="label" text={() => sessionsForAgent(rows)} label="Copy for agent" copiedLabel="Copied for agent" />
    {/if}
  </header>

  <div class="sky-sessions__filters">
    <Input type="search" aria-label="Search sessions" placeholder="Search workflow, phase or ID" bind:value={search} oninput={(e) => onSearch(e.currentTarget.value)} />
    <ToggleGroup type="single" variant="chips" aria-label="Filter by status" bind:value={chipValue} items={chips} />
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
      title={filtered ? 'No sessions match' : 'No sessions yet'}
      description={filtered ? 'Try another search or status, or clear the filters.' : 'Sessions appear here when a workflow runs.'}
    >
      {#snippet action()}
        {#if filtered}<Button onclick={clear}>Clear filters</Button>{:else}<Button href={href('/workflows')}>Run a workflow</Button>{/if}
      {/snippet}
    </EmptyState>
  {:else}
    {#if list.error}
      <Callout tone="warning" title="Showing the last results.">The list could not refresh. <Button size="sm" variant="ghost" onclick={() => list.refresh()}>Retry</Button></Callout>
    {/if}
    <ol class="sky-sessions__list" bind:this={listEl} aria-label="Sessions" aria-busy={list.loading} style:padding-top="{range.padTop}px" style:padding-bottom="{range.padBottom}px">
      {#each visible as s, i (s.id)}
        <li class="sky-sessions__item" aria-setsize={rows.length} aria-posinset={range.start + i + 1}>
          <a class="sky-sessions__row" href={href(`/sessions/${encodeURIComponent(s.id)}`)} use:measure>
            <StatusBadge status={s.status} shape="square" />
            <span class="sky-sessions__name">
              <span class="sky-sessions__workflow">{s.workflow_name ?? s.workflow_id ?? 'Unknown workflow'}</span>
              <span class="sky-sessions__sub">{sessionRowSub(s) || s.id}</span>
            </span>
            <span class="sky-sessions__nums">
              <span class="sky-sessions__num" data-col="tokens"><span class="sky-visually-hidden">Tokens </span>{s.total_tokens_display}</span>
              <span class="sky-sessions__num" data-col="cost"><span class="sky-visually-hidden">Cost </span>{s.total_cost_display}{#if s.unpriced_observation_count}+{/if}</span>
              <span class="sky-sessions__num" data-col="duration"><span class="sky-visually-hidden">Duration </span>{s.duration_display}</span>
              <span class="sky-sessions__num" data-col="when">{formatRelativeTime(s.started_at, { now })}</span>
            </span>
          </a>
        </li>
      {/each}
    </ol>
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
    gap: var(--ds-space-5);
    min-width: 0;
  }
  .sky-sessions__head {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--ds-space-3);
  }
  .sky-sessions__title h1 {
    margin: 0;
    font-size: var(--sky-text-page);
    line-height: 1.08;
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.035em;
  }
  .sky-sessions__title p {
    margin: var(--ds-space-1) 0 0;
    font-size: var(--sky-text-body);
    color: var(--ds-color-text-muted);
  }
  .sky-sessions__count {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
  }
  .sky-sessions__filters {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-sessions__skeleton {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
  }
  .sky-sessions__list {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-sessions__item + .sky-sessions__item {
    border-top: var(--ds-border-width) solid var(--sky-color-divider);
  }
  .sky-sessions__row {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    grid-template-areas:
      'badge name'
      'badge nums';
    align-items: center;
    column-gap: var(--ds-space-3);
    row-gap: var(--ds-space-1);
    box-sizing: border-box;
    height: 5.5rem;
    padding: var(--ds-space-3) var(--ds-space-4);
    color: var(--ds-color-fg);
    text-decoration: none;
  }
  .sky-sessions__row :global(.sky-status-badge),
  .sky-sessions__row > :first-child {
    grid-area: badge;
  }
  .sky-sessions__row:hover {
    background: var(--sky-color-control-hover);
  }
  .sky-sessions__row:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: calc(-1 * var(--sky-focus-ring-width));
    border-radius: var(--sky-radius-row);
  }
  .sky-sessions__name {
    grid-area: name;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .sky-sessions__workflow {
    font-size: var(--sky-text-body);
    font-weight: var(--ds-font-weight-semibold);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-sessions__sub {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-sessions__nums {
    grid-area: nums;
    display: flex;
    gap: var(--ds-space-3);
    min-width: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .sky-sessions__num[data-col='when'] {
    margin-left: auto;
    color: var(--ds-color-text-subtle);
  }
  .sky-sessions__foot {
    margin: 0;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }

  @media (min-width: 48rem) {
    .sky-sessions__filters {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: center;
    }
    .sky-sessions__filters > :global(:first-child) {
      flex: 0 1 20rem;
    }
    .sky-sessions__row {
      grid-template-columns: auto minmax(0, 1fr) auto;
      grid-template-areas: 'badge name nums';
      column-gap: var(--ds-space-4);
      height: 4.5rem;
      padding: 0 var(--ds-space-5);
    }
    .sky-sessions__nums {
      display: grid;
      grid-template-columns: 5rem 5.5rem 4.5rem 5rem;
      gap: var(--ds-space-4);
      font-size: var(--sky-text-data);
      text-align: right;
    }
    .sky-sessions__num[data-col='tokens'],
    .sky-sessions__num[data-col='cost'] {
      color: var(--ds-color-fg);
    }
  }
</style>
