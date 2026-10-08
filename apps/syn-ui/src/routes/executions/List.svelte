<!--
  Executions (boards: Executions, PhoneExecutions). One responsive page:
  base styles are the phone board, the table header and wider hero arrive
  at 48rem. Filters live in the URL (?status=, ?q=, ?window=, ?page=) so a
  link reproduces the view. Live: refetches when an execution event lands.
-->
<script lang="ts">
  import { formatCost, formatRelativeTime, formatTokens } from '@syn137/skyline-core/format'
  import { runBarPercent, runSegments, runSubline } from '@syn137/skyline-core/patterns'
  import {
    EXECUTION_FILTERS,
    TIME_WINDOWS,
    executionsLede,
    executionsLedeShort,
    groupByAge,
    isExecutionEvent,
    listSummary,
    outcomeTotals,
    parseTimeWindow,
    timeWindowStart,
  } from '@syn137/skyline-core/screens/executions'
  import { Button, Callout, EmptyState, Input, Pagination, Skeleton, ToggleGroup } from '@syn137/skyline-svelte-v5'
  import { ObjectIcon, RunRow } from '@syn137/skyline-svelte-v5/patterns'
  import { ApiError, listExecutions } from '@syn137/syn-ui-data'
  import type { ExecutionListResponse } from '@syn137/syn-ui-data/types'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import { href, router } from '../../lib/router'
  import type { PageProps } from '../../lib/routes'

  type Row = ExecutionListResponse['executions'][number]

  let { params: _params }: PageProps = $props()
  setPage({ title: 'Executions', crumbs: [{ label: 'Executions' }] })

  const PAGE_SIZE = 50
  const status = $derived(router.query.get('status') ?? 'all')
  const window = $derived(parseTimeWindow(router.query.get('window')))
  const page = $derived(Math.max(1, Number(router.query.get('page')) || 1))
  const q = $derived(router.query.get('q') ?? '')

  // The search box is local while typing; the URL follows after a pause.
  let search = $state(router.query.get('q') ?? '')
  $effect(() => {
    const next = search.trim()
    if (next === q) return
    const t = setTimeout(() => router.setQuery({ q: next || null, page: null }), 250)
    return () => clearTimeout(t)
  })

  const list = resource(
    (signal) => {
      const query = {
        page,
        page_size: PAGE_SIZE,
        statuses: status === 'all' ? undefined : [status],
        started_after: timeWindowStart(window, Date.now()),
        q: q || undefined,
      }
      return listExecutions(query, signal)
    },
    { live: isExecutionEvent },
  )

  const now = $derived(list.data ? Date.now() : 0)
  const rows = $derived(list.data?.executions ?? [])
  const totals = $derived(outcomeTotals(list.data?.status_counts))
  const longest = $derived(Math.max(0, ...rows.map((r) => (r.duration_seconds ?? 0) * 1000)))
  const groups = $derived(groupByAge(rows, (r) => r.started_at, now || Date.now()))
  const pageCount = $derived(Math.max(1, Math.ceil((list.data?.total ?? 0) / PAGE_SIZE)))
  const outcomeLabel = $derived(`${totals.completed} completed, ${totals.failed} failed, ${totals.cancelled} cancelled`)

  const chips = $derived(
    EXECUTION_FILTERS.filter((f) => f.value === 'all' || f.value === status || (list.data?.status_counts?.[f.value] ?? 0) > 0 || ['running', 'completed', 'failed', 'cancelled'].includes(f.value)).map((f) => ({
      value: f.value,
      label: f.label,
      count: f.value === 'all' ? totals.total : (list.data?.status_counts?.[f.value] ?? 0),
    })),
  )

  const filtered = $derived(status !== 'all' || window !== 'all' || q !== '')

  function rowSub(r: Row): string {
    const repo = r.repos_display ?? null
    return runSubline(repo, r.phase_progress?.completed ?? r.completed_phases, r.phase_progress?.possible ?? r.total_phases)
  }

  function when(r: Row): string {
    if (r.start_queue) return 'queued'
    return formatRelativeTime(r.started_at, { now: now || Date.now() })
  }

  function errorText(e: unknown): string {
    if (e instanceof ApiError) return typeof e.detail === 'string' ? e.detail : `The server answered ${e.status}.`
    return e instanceof Error ? e.message : String(e)
  }

  function clearFilters() {
    search = ''
    router.setQuery({ status: null, window: null, q: null, page: null })
  }
</script>

<div class="sky-execs">
  <section class="sky-execs__hero" aria-label="Executions">
    <div class="sky-execs__intro">
      <ObjectIcon kind="execution" size={84} class="sky-execs__icon" />
      <div class="sky-execs__titles">
        <h1>Executions</h1>
        {#if list.data}
          <p class="sky-execs__lede sky-execs__lede--long">{executionsLede(totals)}</p>
          <p class="sky-execs__lede sky-execs__lede--short">{executionsLedeShort(totals)}</p>
        {:else}
          <Skeleton variant="text" width="16rem" />
        {/if}
      </div>
    </div>
    <div class="sky-execs__outcomes">
      <div class="sky-execs__split" role="img" aria-label={outcomeLabel}>
        {#if totals.completed + totals.failed + totals.cancelled > 0}
          <span data-tone="completed" style:flex-grow={totals.completed}></span>
          <span data-tone="failed" style:flex-grow={totals.failed}></span>
          <span data-tone="cancelled" style:flex-grow={totals.cancelled}></span>
        {:else}
          <span data-tone="empty" style:flex-grow={1}></span>
        {/if}
      </div>
      <div class="sky-execs__figures">
        {#each [['completed', totals.completed], ['failed', totals.failed], ['cancelled', totals.cancelled]] as const as [tone, n] (tone)}
          <div class="sky-execs__figure">
            <span class="sky-execs__figure-value">{list.data ? n : '—'}</span>
            <span class="sky-execs__figure-label"><span class="sky-execs__swatch" data-tone={tone}></span>{tone}</span>
          </div>
        {/each}
      </div>
    </div>
  </section>

  <div class="sky-execs__toolbar">
    <div class="sky-execs__search">
      <Input type="search" aria-label="Search executions" placeholder="Workflow, repo or ID" bind:value={search} />
    </div>
    <ToggleGroup
      class="sky-execs__chips"
      type="single"
      variant="chips"
      aria-label="Status"
      items={chips}
      value={[status]}
      onValueChange={(v) => router.setQuery({ status: v[0] && v[0] !== 'all' ? v[0] : null, page: null })}
    />
    <ToggleGroup
      class="sky-execs__window"
      type="single"
      variant="segmented"
      mono
      aria-label="Time window"
      items={TIME_WINDOWS.map((w) => ({ value: w.value, label: w.label }))}
      value={[window]}
      onValueChange={(v) => router.setQuery({ window: v[0] && v[0] !== 'all' ? v[0] : null, page: null })}
    />
  </div>

  {#if list.error && !list.data}
    <Callout tone="danger" title="Executions did not load." role="alert">
      {errorText(list.error)}
      {#snippet action()}<Button size="sm" onclick={() => list.refresh()}>Retry</Button>{/snippet}
    </Callout>
  {:else if !list.data}
    <section class="sky-execs__list" aria-label="Execution list" aria-busy="true">
      <Skeleton label="Loading executions" variant="block" height="3.5rem" />
      <Skeleton variant="block" height="3.5rem" />
      <Skeleton variant="block" height="3.5rem" />
      <Skeleton variant="block" height="3.5rem" />
    </section>
  {:else if rows.length === 0}
    <EmptyState
      title={filtered ? 'No matching executions' : 'No executions yet'}
      description={filtered ? 'Nothing matches these filters. Widen the time window or clear the filters.' : 'Executions appear here when a workflow runs. Start one from a workflow page.'}
    >
      {#snippet action()}
        {#if filtered}
          <Button onclick={clearFilters}>Clear filters</Button>
        {:else}
          <Button onclick={() => router.navigate(href('/workflows'))}>Go to workflows</Button>
        {/if}
      {/snippet}
    </EmptyState>
  {:else}
    {#if list.error}
      <Callout tone="warning" title="Not updating.">Showing the last list that loaded. {errorText(list.error)}</Callout>
    {/if}
    <section class="sky-execs__list" aria-label="Execution list" aria-busy={list.loading}>
      <div class="sky-execs__head" aria-hidden="true">
        <span></span>
        <span>Workflow</span>
        <span>Phases over time</span>
        <span class="sky-execs__num">Tokens</span>
        <span class="sky-execs__num">Cost</span>
        <span class="sky-execs__num sky-execs__sorted">Started ↓</span>
      </div>
      {#each groups as g (g.title)}
        <div class="sky-execs__group">
          <h2 class="sky-execs__group-title">{g.title}</h2>
          <span class="sky-execs__group-count">{g.count}</span>
          <span class="sky-execs__group-rule"></span>
        </div>
        <ul class="sky-execs__rows">
          {#each g.rows as r (r.workflow_execution_id)}
            <li>
              <RunRow
                href={href(`/executions/${r.workflow_execution_id}`)}
                status={r.status}
                name={r.workflow_name || r.workflow_id}
                sub={rowSub(r)}
                segments={runSegments({ status: r.status, done: r.phase_progress?.completed ?? r.completed_phases, total: r.phase_progress?.possible ?? r.total_phases })}
                barPercent={runBarPercent((r.duration_seconds ?? 0) * 1000, longest)}
                duration={r.duration_display ?? '—'}
                tokens={r.total_tokens_display ?? formatTokens(r.total_tokens)}
                cost={r.total_cost_display ?? formatCost(r.total_cost_usd)}
                when={when(r)}
                aria-label={`${r.workflow_name}, ${r.status}, started ${when(r)}`}
              />
            </li>
          {/each}
        </ul>
      {/each}
    </section>
    <Pagination
      {page}
      {pageCount}
      summary={listSummary(page, PAGE_SIZE, rows.length, list.data.total, status) + (list.data.excluded_undated ? ` · ${list.data.excluded_undated} undated left out` : '')}
      onPageChange={(p) => router.setQuery({ page: p > 1 ? String(p) : null }, { push: true })}
    />
    {#if list.data.budget}
      <p class="sky-execs__budget">Execution budget: {list.data.budget.display}{list.data.budget.admission_paused ? ' · admission paused' : ''}</p>
    {/if}
  {/if}
</div>

<style>
  .sky-execs {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
  }
  .sky-execs__hero {
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
  .sky-execs__intro {
    display: flex;
    align-items: center;
    gap: var(--ds-space-4);
    min-width: 0;
  }
  .sky-execs__intro :global(.sky-execs__icon) {
    display: none;
    flex-shrink: 0;
  }
  .sky-execs__titles {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  h1 {
    margin: 0;
    font-size: var(--sky-text-page);
    line-height: 1.05;
    font-weight: 600;
    letter-spacing: -0.035em;
  }
  .sky-execs__lede {
    margin: 0;
    color: var(--ds-color-text-muted);
  }
  .sky-execs__lede--long {
    display: none;
  }
  .sky-execs__outcomes {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3-5);
    min-width: 0;
  }
  .sky-execs__split {
    display: flex;
    gap: 3px;
    height: 12px;
  }
  .sky-execs__split > span {
    flex-basis: 0;
    border-radius: 4px;
  }
  [data-tone='completed'] {
    background: var(--ds-color-accent);
  }
  [data-tone='failed'] {
    background: var(--ds-color-danger);
  }
  [data-tone='cancelled'] {
    background: var(--ds-color-text-subtle);
  }
  [data-tone='empty'] {
    background: var(--sky-color-track);
  }
  .sky-execs__figures {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--ds-space-4);
  }
  .sky-execs__figure {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .sky-execs__figure-value {
    font-size: var(--sky-text-figure);
    line-height: 1.1;
    font-weight: 600;
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
  }
  .sky-execs__figure-label {
    display: flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-execs__swatch {
    width: 8px;
    height: 8px;
    border-radius: 2px;
  }
  .sky-execs__toolbar {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-execs__toolbar > :global(*) {
    min-width: 0;
  }
  .sky-execs__list {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-execs__head {
    display: none;
  }
  .sky-execs__group {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    min-height: 30px;
    margin-top: var(--ds-space-1-5);
    padding: 0 var(--ds-space-1);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-execs__group-title {
    margin: 0;
    font: inherit;
    color: var(--ds-color-text-muted);
  }
  .sky-execs__group-count {
    color: var(--ds-color-text-subtle);
  }
  .sky-execs__group-rule {
    flex-grow: 1;
    height: 1px;
    background: var(--ds-color-border);
  }
  .sky-execs__rows {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-execs__budget {
    margin: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }

  @media (min-width: 48rem) {
    .sky-execs {
      gap: var(--ds-space-6);
    }
    .sky-execs__hero {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--ds-space-7) var(--ds-space-12);
      padding: var(--ds-space-8) var(--ds-space-9);
    }
    .sky-execs__intro {
      gap: var(--ds-space-6);
    }
    .sky-execs__intro :global(.sky-execs__icon) {
      display: block;
    }
    .sky-execs__lede--long {
      display: block;
    }
    .sky-execs__lede--short {
      display: none;
    }
    .sky-execs__outcomes {
      width: 22.5rem;
      max-width: 100%;
    }
    .sky-execs__toolbar {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--ds-space-3) var(--ds-space-4);
    }
    .sky-execs__toolbar > :global(.sky-execs__chips) {
      order: -1;
      flex: 1 1 auto;
    }
    .sky-execs__search {
      width: 15rem;
    }
    .sky-execs__list {
      gap: 2px;
      padding: var(--ds-space-2-5);
      border-radius: var(--sky-radius-card-lg);
      border: var(--ds-border-width) solid var(--ds-color-border);
      background: var(--ds-color-surface);
      box-shadow: var(--sky-shadow-raised);
    }
    .sky-execs__rows {
      gap: 2px;
    }
    .sky-execs__head {
      display: grid;
      grid-template-columns: var(--sky-size-control-sm) minmax(10rem, 1.1fr) minmax(10rem, 1.5fr) 4.5rem 4rem 4rem;
      column-gap: var(--ds-space-4);
      align-items: center;
      height: 36px;
      padding: 0 var(--ds-space-3);
      font-family: var(--ds-font-mono);
      font-size: var(--sky-text-label);
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--ds-color-text-subtle);
    }
    .sky-execs__num {
      text-align: right;
    }
    .sky-execs__sorted {
      color: var(--ds-color-fg);
    }
    .sky-execs__group {
      padding: 0 var(--ds-space-3);
    }
  }
</style>
