<!--
  Workflow runs (boards: Executions, PhoneExecutions, filtered to one
  workflow). GET /workflows/{id}/runs returns every run at once (it declares
  no paging, #1313), so the status chips, time window and pages are client
  side through skyline-core runsView. Filters live in the URL (?status=,
  ?window=, ?page=). Live: refetches when a run event lands.
-->
<script lang="ts">
  import { formatCost, formatDuration, formatRelativeTime, formatTokens } from '@syn137/skyline-core/format'
  import { runBarPercent, runSegments } from '@syn137/skyline-core/patterns'
  import { TIME_WINDOWS, groupByAge, parseTimeWindow } from '@syn137/skyline-core/screens/executions'
  import { RUN_FILTERS, parseRunFilter, runDurationMs, runsSummary, runsView } from '@syn137/skyline-core/screens/workflows'
  import { Button, Callout, EmptyState, Pagination, Skeleton, ToggleGroup } from '@syn137/skyline-svelte-v5'
  import { ObjectIcon, RunRow } from '@syn137/skyline-svelte-v5/patterns'
  import { ApiError, getWorkflow, listWorkflowRuns } from '@syn137/syn-ui-data'
  import { isRunEvent } from '@syn137/syn-ui-data/live'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import { href, router } from '../../lib/router'
  import type { PageProps } from '../../lib/routes'

  let { params }: PageProps = $props()
  const id = $derived(params.workflowId ?? '')
  const wf = resource((signal) => getWorkflow(id, signal))
  const runs = resource((signal) => listWorkflowRuns(id, signal), { live: isRunEvent })

  $effect(() => {
    if (wf.data)
      setPage({
        title: `${wf.data.name} runs`,
        crumbs: [{ label: 'Workflows', href: '/workflows' }, { label: wf.data.name, href: `/workflows/${wf.data.id}` }, { label: 'Runs' }],
      })
  })

  const PAGE_SIZE = 50
  const status = $derived(parseRunFilter(router.query.get('status')))
  const window = $derived(parseTimeWindow(router.query.get('window')))
  const page = $derived(Math.max(1, Number(router.query.get('page')) || 1))

  const now = $derived(runs.data ? Date.now() : 0)
  const view = $derived(runsView(runs.data ?? [], { status, window, page, pageSize: PAGE_SIZE, now: now || Date.now() }))
  const groups = $derived(groupByAge(view.rows, (r) => r.started_at, now || Date.now()))
  const chips = $derived(RUN_FILTERS.map((f) => ({ value: f.value, label: f.label, count: view.counts[f.value] })))
  const filtered = $derived(status !== 'all' || window !== 'all')
  const name = $derived(wf.data?.name ?? id)

  function errorText(e: unknown): string {
    if (e instanceof ApiError) return typeof e.detail === 'string' ? e.detail : `The server answered ${e.status}.`
    return e instanceof Error ? e.message : String(e)
  }
</script>

<div class="sky-wruns">
  <section class="sky-wruns__hero" aria-label="Runs">
    <ObjectIcon kind="execution" size={64} class="sky-wruns__icon" />
    <div class="sky-wruns__titles">
      <span class="sky-wruns__eyebrow">{id}</span>
      <h1>Runs</h1>
      <p>
        {#if runs.data}{runs.data.length} {runs.data.length === 1 ? 'run' : 'runs'} of <a href={href(`/workflows/${id}`)}>{name}</a>{:else}Every run of <a href={href(`/workflows/${id}`)}>{name}</a>{/if}
      </p>
    </div>
  </section>

  <div class="sky-wruns__toolbar">
    <ToggleGroup
      type="single"
      variant="chips"
      aria-label="Status"
      items={chips}
      value={[status]}
      onValueChange={(v) => router.setQuery({ status: v[0] && v[0] !== 'all' ? v[0] : null, page: null })}
    />
    <ToggleGroup
      type="single"
      variant="segmented"
      mono
      aria-label="Time window"
      items={TIME_WINDOWS.map((w) => ({ value: w.value, label: w.label }))}
      value={[window]}
      onValueChange={(v) => router.setQuery({ window: v[0] && v[0] !== 'all' ? v[0] : null, page: null })}
    />
  </div>

  {#if runs.error && !runs.data}
    <Callout tone="danger" title="Runs did not load." role="alert">
      {errorText(runs.error)}
      {#snippet action()}<Button size="sm" onclick={() => runs.refresh()}>Retry</Button>{/snippet}
    </Callout>
  {:else if !runs.data}
    <section class="sky-wruns__list" aria-label="Run list" aria-busy="true">
      <Skeleton label="Loading runs" variant="block" height="3.5rem" />
      <Skeleton variant="block" height="3.5rem" />
      <Skeleton variant="block" height="3.5rem" />
    </section>
  {:else if view.rows.length === 0}
    <EmptyState
      title={filtered ? 'No matching runs' : 'No runs yet'}
      description={filtered ? 'Nothing matches these filters. Widen the time window or clear the filters.' : 'Runs appear here when this workflow runs. Start one from the workflow page.'}
    >
      {#snippet action()}
        {#if filtered}
          <Button onclick={() => router.setQuery({ status: null, window: null, page: null })}>Clear filters</Button>
        {:else}
          <Button href={href(`/workflows/${id}`)}>Go to the workflow</Button>
        {/if}
      {/snippet}
    </EmptyState>
  {:else}
    {#if runs.error}
      <Callout tone="warning" title="Not updating.">Showing the last list that loaded. {errorText(runs.error)}</Callout>
    {/if}
    <section class="sky-wruns__list" aria-label="Run list" aria-busy={runs.loading}>
      <div class="sky-wruns__head" aria-hidden="true">
        <span></span>
        <span>Run</span>
        <span>Phases over time</span>
        <span class="sky-wruns__num">Tokens</span>
        <span class="sky-wruns__num">Cost</span>
        <span class="sky-wruns__num">Started ↓</span>
      </div>
      {#each groups as g (g.title)}
        <div class="sky-wruns__group">
          <h2>{g.title}</h2>
          <span class="sky-wruns__count">{g.count}</span>
          <span class="sky-wruns__rule"></span>
        </div>
        <ul class="sky-wruns__rows">
          {#each g.rows as r (r.workflow_execution_id)}
            {@const ms = runDurationMs(r, now || Date.now())}
            {@const when = formatRelativeTime(r.started_at, { now: now || Date.now() })}
            <li>
              <RunRow
                href={href(`/executions/${r.workflow_execution_id}`)}
                status={r.status}
                name={r.workflow_execution_id}
                sub={r.phase_progress?.display ?? `${r.completed_phases} of ${r.total_phases} phases`}
                segments={runSegments({ status: r.status, done: r.phase_progress?.completed ?? r.completed_phases, total: r.phase_progress?.possible ?? r.total_phases })}
                barPercent={runBarPercent(ms, view.longestMs)}
                duration={formatDuration(ms)}
                tokens={formatTokens(r.total_tokens)}
                cost={formatCost(r.total_cost_usd)}
                {when}
                aria-label={`${r.workflow_execution_id}, ${r.status}, started ${when}`}
              />
            </li>
          {/each}
        </ul>
      {/each}
    </section>
    <Pagination
      page={view.page}
      pageCount={view.pageCount}
      summary={runsSummary(view, PAGE_SIZE, status)}
      onPageChange={(p) => router.setQuery({ page: p > 1 ? String(p) : null }, { push: true })}
    />
  {/if}
</div>

<style>
  .sky-wruns {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
  }
  .sky-wruns__hero {
    display: flex;
    align-items: center;
    gap: var(--ds-space-4);
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-2xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background:
      radial-gradient(50% 130% at 100% 0%, var(--sky-color-accent-soft), transparent 70%),
      var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-wruns__hero :global(.sky-wruns__icon) {
    display: none;
    flex-shrink: 0;
  }
  .sky-wruns__titles {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1-5);
    min-width: 0;
  }
  .sky-wruns__eyebrow {
    overflow: hidden;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  h1 {
    margin: 0;
    font-size: var(--sky-text-page);
    line-height: 1.05;
    font-weight: 600;
    letter-spacing: -0.035em;
  }
  .sky-wruns__titles p {
    margin: 0;
    color: var(--ds-color-text-muted);
  }
  .sky-wruns__titles a {
    color: var(--ds-color-fg);
  }
  .sky-wruns__titles a:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-wruns__toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-wruns__list {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-wruns__head {
    display: none;
  }
  .sky-wruns__group {
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
  .sky-wruns__group h2 {
    margin: 0;
    font: inherit;
  }
  .sky-wruns__count {
    color: var(--ds-color-text-subtle);
  }
  .sky-wruns__rule {
    flex-grow: 1;
    height: 1px;
    background: var(--ds-color-border);
  }
  .sky-wruns__rows {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  @media (min-width: 48rem) {
    .sky-wruns {
      gap: var(--ds-space-6);
    }
    .sky-wruns__hero {
      gap: var(--ds-space-6);
      padding: var(--ds-space-8) 36px;
    }
    .sky-wruns__hero :global(.sky-wruns__icon) {
      display: block;
    }
    .sky-wruns__list {
      gap: 2px;
      padding: var(--ds-space-2-5);
      border-radius: var(--sky-radius-card-lg);
      border: var(--ds-border-width) solid var(--ds-color-border);
      background: var(--ds-color-surface);
      box-shadow: var(--sky-shadow-raised);
    }
    .sky-wruns__rows {
      gap: 2px;
    }
    .sky-wruns__head {
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
    .sky-wruns__num {
      text-align: right;
    }
    .sky-wruns__group {
      padding: 0 var(--ds-space-3);
    }
  }
</style>
