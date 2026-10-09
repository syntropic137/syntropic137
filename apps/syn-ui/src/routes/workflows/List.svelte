<!--
  Workflows (boards: Workflows, PhoneWorkflows). One responsive page: base
  styles are the phone board; the hero turns into a row and the grid widens
  from 48rem. Filter, sort, search and page live in the URL.

  Each card's duration graph and Faster / Slower / Steady label come from
  GET /workflows/{id}/trend for the cards on screen, four at a time (API gap:
  the list should carry each workflow's recent durations).

  The list endpoint has no skills, so the skill chips and "Has skills"
  come from each workflow's detail, fetched four at a time after the list
  renders (API gap: add declared skill names to WorkflowSummary).
-->
<script lang="ts">
  import {
    CATEGORY_ICON,
    DURATION_TREND_PENDING,
    TREND_WINDOW,
    durationTrend,
    WORKFLOW_FILTERS,
    filterWorkflows,
    parseWorkflowFilter,
    parseWorkflowSort,
    phasesLabel,
    runsLabel,
    workflowCategory,
    workflowSkillNames,
    workflowsSummary,
  } from '@syn137/skyline-core/screens/workflows'
  import { Button, Callout, EmptyState, Input, Pagination, Select, Skeleton, ToggleGroup } from '@syn137/skyline-svelte-v5'
  import { ObjectIcon, TrendSpark } from '@syn137/skyline-svelte-v5/patterns'
  import { ApiError, getWorkflow, getWorkflowTrend, isAbortError, listWorkflows, mapLimit, type WorkflowSummary, type WorkflowTrendRow, MAX_PAGE_SIZE } from '@syn137/syn-ui-data'
  import { untrack } from 'svelte'
  import { isRunEvent } from '@syn137/syn-ui-data/live'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import { href, router } from '../../lib/router'
  import type { PageProps } from '../../lib/routes'

  let { params: _params }: PageProps = $props()
  setPage({ title: 'Workflows', crumbs: [{ label: 'Workflows' }] })

  const PAGE_SIZE = 12
  const filter = $derived(parseWorkflowFilter(router.query.get('filter')))
  const sort = $derived(parseWorkflowSort(router.query.get('sort')))
  const page = $derived(Math.max(1, Number(router.query.get('page')) || 1))
  const q = $derived(router.query.get('q') ?? '')

  let search = $state(router.query.get('q') ?? '')
  $effect(() => {
    const next = search.trim()
    if (next === q) return
    const t = setTimeout(() => router.setQuery({ q: next || null, page: null }), 250)
    return () => clearTimeout(t)
  })

  // Whole catalogue at once: filtering by skills and sorting by runs are client side.
  const list = resource((signal) => listWorkflows({ page_size: MAX_PAGE_SIZE }, signal), { live: isRunEvent })

  let skills = $state<Record<string, string[]>>({})
  $effect(() => {
    const rows = list.data?.workflows ?? []
    if (!rows.length) return
    const controller = new AbortController()
    void mapLimit(rows, 4, async (w) => {
      try {
        const d = await getWorkflow(w.id, controller.signal)
        skills = { ...skills, [w.id]: workflowSkillNames(d.phases) }
      } catch (e) {
        if (!isAbortError(e)) skills = { ...skills, [w.id]: [] }
      }
    })
    return () => controller.abort()
  })

  const all = $derived(list.data?.workflows ?? [])
  const matched = $derived(filterWorkflows(all, { filter, sort, search: q, skillsOf: (id) => skills[id] }))
  const pageCount = $derived(Math.max(1, Math.ceil(matched.length / PAGE_SIZE)))
  const rows = $derived(matched.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE))

  let trends = $state<Record<string, WorkflowTrendRow[]>>({})
  // Keyed on the ids on screen, so a skills update that rebuilds `rows` does not abort these.
  const trendIds = $derived(rows.filter((w) => w.runs_count > 0).map((w) => w.id).join(' '))
  $effect(() => {
    const need = trendIds.split(' ').filter((id) => id && untrack(() => !(id in trends)))
    if (!need.length) return
    const controller = new AbortController()
    void mapLimit(need, 4, async (id) => {
      try {
        const res = await getWorkflowTrend(id, { page_size: TREND_WINDOW }, controller.signal)
        trends = { ...trends, [id]: res.items }
      } catch (e) {
        if (!isAbortError(e)) trends = { ...trends, [id]: [] }
      }
    })
    return () => controller.abort()
  })
  const trendOf = (w: WorkflowSummary) => {
    if (w.runs_count === 0) return durationTrend([], 0)
    const t = trends[w.id]
    return t ? durationTrend(t, w.runs_count) : DURATION_TREND_PENDING
  }
  const filtered = $derived(filter !== 'all' || q !== '')
  const skillsPending = $derived(filter === 'skills' && all.some((w) => !(w.id in skills)))

  const chips = $derived(WORKFLOW_FILTERS.map((f) => (f.value === 'all' ? { value: f.value, label: f.label, count: all.length } : { value: f.value, label: f.label })))

  function errorText(e: unknown): string {
    if (e instanceof ApiError) return typeof e.detail === 'string' ? e.detail : `The server answered ${e.status}.`
    return e instanceof Error ? e.message : String(e)
  }

  function clearFilters() {
    search = ''
    router.setQuery({ filter: null, q: null, page: null })
  }
</script>

<div class="sky-wfs">
  <section class="sky-wfs__hero" aria-label="Workflows">
    <div class="sky-wfs__intro">
      <ObjectIcon kind="workflow" size={84} class="sky-wfs__icon" />
      <div class="sky-wfs__titles">
        <h1>Workflows</h1>
        {#if list.data}
          <p class="sky-wfs__lede sky-wfs__lede--long">{list.data.total} phased definitions your agents can run. Pick one to start it or edit its prompts.</p>
          <p class="sky-wfs__lede sky-wfs__lede--short">{list.data.total} definitions your agents can run</p>
        {:else}
          <Skeleton variant="text" width="16rem" />
        {/if}
      </div>
    </div>
    <div class="sky-wfs__controls">
      <div class="sky-wfs__search">
        <Input type="search" aria-label="Search workflows" placeholder="Search by name or ID" bind:value={search} />
      </div>
      <div class="sky-wfs__sort">
        <Select
          aria-label="Sort"
          label="Sort"
          options={[
            { value: 'runs', label: 'Most run' },
            { value: 'name', label: 'Name' },
          ]}
          value={sort}
          onValueChange={(v) => router.setQuery({ sort: v === 'name' ? 'name' : null, page: null })}
        />
      </div>
    </div>
  </section>

  <ToggleGroup
    class="sky-wfs__chips"
    type="single"
    variant="chips"
    aria-label="Filter workflows"
    items={chips}
    value={[filter]}
    onValueChange={(v) => router.setQuery({ filter: v[0] && v[0] !== 'all' ? v[0] : null, page: null })}
  />

  {#if list.error && !list.data}
    <Callout tone="danger" title="Workflows did not load." role="alert">
      {errorText(list.error)}
      {#snippet action()}<Button size="sm" onclick={() => list.refresh()}>Retry</Button>{/snippet}
    </Callout>
  {:else if !list.data || (skillsPending && rows.length === 0)}
    <section class="sky-wfs__grid" aria-label="Workflow list" aria-busy="true">
      <Skeleton label="Loading workflows" variant="block" height="13rem" />
      <Skeleton variant="block" height="13rem" />
      <Skeleton variant="block" height="13rem" />
    </section>
  {:else if rows.length === 0}
    <EmptyState
      title={filtered ? 'No matching workflows' : 'No workflows yet'}
      description={filtered ? 'Nothing matches this filter or search. Clear it to see every workflow.' : 'Seed workflows with `just seed-workflows`, or add one with `syn workflow create`.'}
    >
      {#snippet action()}
        {#if filtered}<Button onclick={clearFilters}>Clear filters</Button>{/if}
      {/snippet}
    </EmptyState>
  {:else}
    {#if list.error}
      <Callout tone="warning" title="Not updating.">Showing the last list that loaded. {errorText(list.error)}</Callout>
    {/if}
    <ul class="sky-wfs__grid" aria-label="Workflow list" aria-busy={list.loading}>
      {#each rows as w (w.id)}
        {@const cat = workflowCategory(w.workflow_type)}
        {@const names = skills[w.id] ?? []}
        {@const trend = trendOf(w)}
        <li class="sky-wfs__card" data-sky-row>
          <div class="sky-wfs__top">
            <span class="sky-wfs__type">
              <span class="sky-wfs__type-icon">
                <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d={CATEGORY_ICON[cat]}></path></svg>
              </span>
              <span>{cat}</span>
            </span>
            <span class="sky-wfs__runs" data-none={w.runs_count === 0 || undefined}>{runsLabel(w.runs_count)}</span>
          </div>
          <a class="sky-wfs__name" href={href(`/workflows/${w.id}`)}>
            <span class="sky-wfs__title">{w.name}</span>
            <span class="sky-wfs__slug">{w.id}</span>
          </a>
          {#if names.length}
            <ul class="sky-wfs__skills" aria-label="Skills">
              {#each names as s (s)}
                <li class="sky-wfs__skill">
                  <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M8 1.75L14.25 8 8 14.25 1.75 8z"></path></svg>
                  <span>{s}</span>
                </li>
              {/each}
            </ul>
          {/if}
          <div class="sky-wfs__bottom">
            <div class="sky-wfs__phases">
              <span class="sky-wfs__pips" aria-hidden="true">
                {#each Array.from({ length: w.phase_count }, (_, i) => i) as i (i)}<span></span>{/each}
              </span>
              <span class="sky-wfs__phase-count">{phasesLabel(w.phase_count)}</span>
            </div>
            <span class="sky-wfs__rule" aria-hidden="true"></span>
            <span class="sky-wfs__trend"><TrendSpark kind={trend.kind} word={trend.word} sub={trend.sub} label={trend.label} spark={trend.spark} /></span>
            <a class="sky-wfs__run" href={href(`/workflows/${w.id}`)} aria-label="Run {w.name}">
              <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M4.5 2.75v10.5L13 8z"></path></svg>
              <span>Run</span>
            </a>
          </div>
        </li>
      {/each}
    </ul>
    <Pagination
      {page}
      {pageCount}
      summary={workflowsSummary(rows.length, matched.length, filter)}
      onPageChange={(p) => router.setQuery({ page: p > 1 ? String(p) : null }, { push: true })}
    />
  {/if}
</div>

<style>
  .sky-wfs {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
  }
  .sky-wfs__hero {
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
  .sky-wfs__intro {
    display: flex;
    align-items: center;
    gap: var(--ds-space-4);
    min-width: 0;
  }
  .sky-wfs__intro :global(.sky-wfs__icon) {
    display: none;
    flex-shrink: 0;
  }
  .sky-wfs__titles {
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
  .sky-wfs__lede {
    margin: 0;
    color: var(--ds-color-text-muted);
  }
  .sky-wfs__lede--long {
    display: none;
  }
  .sky-wfs__controls {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--ds-space-2-5);
    min-width: 0;
  }
  .sky-wfs__search {
    flex: 1 1 14rem;
    min-width: 0;
  }
  .sky-wfs__sort {
    flex: 0 1 auto;
  }
  .sky-wfs__grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr));
    gap: var(--ds-space-3-5);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-wfs__card {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
    transition: border-color var(--sky-duration-fast) ease;
  }
  .sky-wfs__card:hover {
    border-color: var(--sky-color-border-hover);
  }
  .sky-wfs__top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-3);
  }
  .sky-wfs__type {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-wfs__type-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: 9px;
    background: var(--sky-color-accent-soft);
    color: var(--ds-color-accent);
  }
  .sky-wfs__runs {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-fg);
  }
  .sky-wfs__runs[data-none] {
    color: var(--ds-color-text-subtle);
  }
  .sky-wfs__name {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
    flex-grow: 1;
    min-width: 0;
    color: var(--ds-color-fg);
    text-decoration: none;
    border-radius: var(--ds-radius-md);
  }
  .sky-wfs__name:focus-visible,
  .sky-wfs__run:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-wfs__title {
    font-size: 17px;
    line-height: 1.3;
    font-weight: 600;
    letter-spacing: -0.01em;
    text-wrap: balance;
  }
  .sky-wfs__slug {
    overflow: hidden;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .sky-wfs__skills {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-wfs__skill {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 24px;
    padding: 0 9px 0 7px;
    border-radius: 8px;
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-surface-raised);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-fg);
  }
  .sky-wfs__skill svg {
    color: var(--ds-color-accent);
  }
  .sky-wfs__bottom {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas: 'trend trend' 'phases run';
    align-items: center;
    gap: var(--ds-space-3-5);
  }
  .sky-wfs__trend {
    grid-area: trend;
    display: flex;
    min-width: 0;
    padding: 2px 0;
  }
  .sky-wfs__rule {
    display: none;
    grid-area: rule;
    border-top: var(--ds-border-width) solid var(--ds-color-border);
  }
  .sky-wfs__phases {
    grid-area: phases;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: var(--ds-space-3);
  }
  .sky-wfs__pips {
    display: flex;
    flex-grow: 1;
    gap: 4px;
  }
  .sky-wfs__pips > span {
    flex: 0 0 22px;
    height: 8px;
    border-radius: 3px;
    background: var(--sky-face-front);
    box-shadow: inset 0 1px 0 var(--sky-face-top);
  }
  .sky-wfs__phase-count {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-wfs__run {
    grid-area: run;
    display: flex;
    align-items: center;
    gap: 7px;
    height: var(--sky-size-control-sm);
    padding: 0 var(--ds-space-3);
    border-radius: var(--ds-radius-md);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-surface-raised);
    color: var(--ds-color-fg);
    font-size: var(--ds-text-sm);
    font-weight: 600;
    text-decoration: none;
  }
  .sky-wfs__run:hover {
    border-color: var(--sky-color-border-hover);
  }
  .sky-wfs__run svg {
    color: var(--ds-color-accent);
  }
  @media (pointer: coarse) {
    .sky-wfs__run {
      min-height: var(--sky-size-touch);
    }
  }
  @media (min-width: 48rem) {
    .sky-wfs {
      gap: var(--ds-space-6);
    }
    .sky-wfs__hero {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--ds-space-7) var(--ds-space-12);
      padding: var(--ds-space-8) 36px;
    }
    .sky-wfs__intro {
      gap: var(--ds-space-6);
    }
    .sky-wfs__intro :global(.sky-wfs__icon) {
      display: block;
    }
    .sky-wfs__lede--long {
      display: block;
    }
    .sky-wfs__lede--short {
      display: none;
    }
    .sky-wfs__search {
      flex: 0 1 260px;
    }
    .sky-wfs__bottom {
      grid-template-areas: 'phases phases' 'rule rule' 'trend run';
      row-gap: var(--ds-space-4);
    }
    .sky-wfs__rule {
      display: block;
    }
    .sky-wfs__pips > span {
      flex: 1 1 0;
      max-width: 46px;
    }
  }
</style>
