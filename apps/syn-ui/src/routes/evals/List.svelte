<!-- Evals list. Boards: Evals · PhoneEvals. Verdict board over every eval, then the tag-filterable list. -->
<script lang="ts">
  import { listEvalRuns, listEvals, MAX_PAGE_SIZE } from '@syn137/syn-ui-data'
  import type { EvalSummary } from '@syn137/syn-ui-data'
  import { Callout, EmptyState, Pagination, Skeleton } from '@syn137/skyline-svelte-v5'
  import { PageHeader, VerdictBlock, VerdictBoard, VerdictSparkline } from '@syn137/skyline-svelte-v5/patterns'
  import { formatDate, formatRelativeTime } from '@syn137/skyline-core/format'
  import { cellKey, normalizeVerdict } from '@syn137/skyline-core/patterns'
  import { buildEvalBoard, filterEvals, pageOf, recentVerdicts, sortEvalsByLastRun, tagValue, withLatestRun } from '@syn137/skyline-core/screens/evals'
  import { isRunFinished } from '@syn137/syn-ui-data/live'
  import { resource } from '../../lib/load.svelte'
  import { href, router } from '../../lib/router'
  import type { PageProps } from '../../lib/routes'
  import EvalTag from './EvalTag.svelte'
  import FlaskIcon from './FlaskIcon.svelte'

  let { params: _params }: PageProps = $props()

  const PAGE_SIZE = 20

  const tag = $derived(router.query.get('tag') ?? '')
  const page = $derived.by(() => {
    const n = Number(router.query.get('page') ?? '1')
    return Number.isInteger(n) && n > 0 ? n : 1
  })

  // One /evals load per visit (it takes ~20 s on a large deployment): the
  // board, the tag filter, the list and its pages are all derived from it.
  const all = resource((signal) => listEvals({ page_size: MAX_PAGE_SIZE }, signal), { live: isRunFinished })
  const sorted = $derived(sortEvalsByLastRun(all.data?.evals ?? []))
  const filtered = $derived(filterEvals(sorted, tag))
  const paged = $derived(pageOf(filtered, page, PAGE_SIZE))

  const board = $derived(
    buildEvalBoard(all.data?.evals ?? [], {
      evalHref: (id) => href(`/evals/${encodeURIComponent(id)}`),
      caseSub: (_id, evs) => {
        const repo = evs[0] && 'baseline_repos' in evs[0] ? (evs[0] as EvalSummary).baseline_repos[0] : undefined
        const pr = evs.map((e) => e.tags.find((t) => t.startsWith('pr:'))).find(Boolean)
        return repo ? [pr ? `PR #${pr.slice(3)}` : null, repo.commit_sha.slice(0, 7)].filter(Boolean).join(' · ') : undefined
      },
    }),
  )

  let selected = $state<string | null>(null)
  const firstKey = $derived(board.cases[0] && board.verifiers[0] ? cellKey(board.cases[0].id, board.verifiers[0].id) : null)
  const pickKey = $derived(selected ?? firstKey)
  const pickEvalId = $derived(pickKey ? board.evalIds[pickKey] : undefined)
  const pickWorkflow = $derived(pickKey ? board.workflows[pickKey] : undefined)

  // The readout shows the latest run of the selected cell's workflow: evidence, duration, links.
  // A stable-id eval holds every verifier, so its newest run may belong to another column.
  const pickRun = resource((signal) => {
    const id = pickEvalId
    return id ? listEvalRuns(id, { page_size: 50 }, signal) : Promise.resolve(null)
  })

  const cells = $derived.by(() => {
    if (!pickKey) return board.cells
    const items = pickRun.data?.items ?? []
    const run = items.find((r) => r.workflow_id === pickWorkflow) ?? items[0]
    if (!run || !pickEvalId || board.evalIds[pickKey] !== pickEvalId) return board.cells
    return {
      ...board.cells,
      [pickKey]: withLatestRun(board.cells[pickKey], run, {
        date: run.started_at ? formatDate(run.started_at) : undefined,
        runHref: href(`/executions/${encodeURIComponent(run.execution_id)}`),
      }),
    }
  })

  let search = $state('')
  $effect(() => {
    search = tag
  })

  function setTag(next: string | null) {
    router.setQuery({ tag: next, page: null }, { push: true })
  }
  function onsubmit(e: SubmitEvent) {
    e.preventDefault()
    setTag(search.trim() || null)
  }

  const total = $derived(all.data?.total)
  const caseCount = $derived(board.cases.length)
  const boardDescription = $derived(
    `Does the verifier block a change that carries a known escaped bug, and name the defect and the file it lives in? ${caseCount} ${caseCount === 1 ? 'case' : 'cases'}, each pinned to the commit before its fix, under ${board.verifiers.length} ${board.verifiers.length === 1 ? 'verifier' : 'verifiers'}.`,
  )
  const pageCount = $derived(paged.pageCount)
  const rangeSummary = $derived.by(() => {
    if (filtered.length === 0) return ''
    const to = paged.from + paged.rows.length - 1
    const loaded = all.data && all.data.total > all.data.evals.length ? ` (first ${all.data.evals.length} of ${all.data.total} loaded)` : ''
    return `Showing ${paged.from}–${to} of ${filtered.length} evals${loaded}`
  })

  function variantLine(e: EvalSummary) {
    return (e.variants ?? []).map((v) => ({ key: `${v.workflow_id}@${v.workflow_version}|${v.models.join(',')}`, wf: v.workflow_id, model: v.models.join(', '), pass: v.pass_rate_display }))
  }
</script>

<PageHeader
  kind="eval"
  title="Evals"
  description={`Stable cases run again and again, so the same goal can be compared across workflows and models over time.${total !== undefined ? ` ${total} ${total === 1 ? 'eval' : 'evals'}.` : ''}`}
>
  <form class="sky-evals__search" role="search" {onsubmit}>
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><circle cx="7" cy="7" r="4.25"></circle><path d="M10.25 10.25L13.5 13.5"></path></svg>
    <input type="search" aria-label="Filter evals by name or tag" placeholder="Filter, e.g. case:codex-cost-limit or esp" bind:value={search} />
  </form>
</PageHeader>

{#if all.error && !all.data}
  <Callout tone="danger" title="Could not load evals">{all.error instanceof Error ? all.error.message : String(all.error)}</Callout>
{:else if !all.data}
  <section class="sky-evals__panel" aria-busy="true" aria-label="Loading verdict board">
    <p class="sky-evals__wait" role="status">Loading every eval. On a large deployment this can take about 20 s.</p>
    <Skeleton variant="title" width="12rem" />
    <Skeleton variant="text" lines={2} />
    <Skeleton variant="block" height="18rem" />
  </section>
{:else if board.cases.length > 0}
  <VerdictBoard
    suite={board.suite ?? undefined}
    description={boardDescription}
    cases={board.cases}
    verifiers={board.verifiers}
    {cells}
    bind:selected
  />
{/if}

<section class="sky-evals__all" aria-labelledby="sky-evals-all">
  <div class="sky-evals__all-head">
    <div class="sky-evals__all-title">
      <h2 id="sky-evals-all">All evals</h2>
      <span>Newest run first. Select a tag, or type part of a name or tag, to filter.</span>
    </div>
    {#if tag}
      <div class="sky-evals__tagged">
        <span>Tagged</span>
        <EvalTag {tag} removable onremove={() => setTag(null)} />
      </div>
    {/if}
  </div>

  {#if all.error && !all.data}
    <Callout tone="danger" title="Could not load evals">{all.error instanceof Error ? all.error.message : String(all.error)}</Callout>
  {:else if !all.data}
    <div class="sky-evals__list" aria-busy="true" aria-label="Loading evals">
      {#each [0, 1, 2, 3] as i (i)}
        <div class="sky-evals__row"><Skeleton variant="block" width="2.75rem" height="2.4rem" /><div class="sky-evals__row-body"><Skeleton variant="text" lines={3} /></div></div>
      {/each}
    </div>
  {:else if paged.rows.length === 0}
    <div class="sky-evals__list">
      {#if filtered.length > 0}
        <EmptyState title="No evals on this page" description={`There are ${filtered.length} evals.`}>
          {#snippet icon()}<FlaskIcon />{/snippet}
          {#snippet action()}<a href={href(tag ? `/evals?tag=${encodeURIComponent(tag)}` : '/evals')}>Back to page 1</a>{/snippet}
        </EmptyState>
      {:else}
        <EmptyState
          title={tag ? `No evals match ${tag}` : 'No evals yet'}
          description="Create one with scripts/eval_suite.py launch, or POST /evals with a goal and a pinned baseline repo. Each execution launched into it becomes a run here."
        >
          {#snippet icon()}<FlaskIcon />{/snippet}
        </EmptyState>
      {/if}
    </div>
  {:else}
    <ul class="sky-evals__list" aria-busy={all.loading}>
      {#each paged.rows as e (e.eval_id)}
        {@const recent = recentVerdicts(e)}
        {@const verdict = e.run_count > 0 ? normalizeVerdict(e.last_verdict) : 'unscored'}
        <li class="sky-evals__row" data-sky-row>
          <VerdictBlock class="sky-evals__block" {verdict} size={44} />
          <div class="sky-evals__row-body">
            <div class="sky-evals__row-top">
              <span class="sky-evals__title">
                <a class="sky-evals__name" href={href(`/evals/${encodeURIComponent(e.eval_id)}`)}>{e.name}</a>
                {#if e.archived}<span class="sky-evals__archived">Archived</span>{/if}
              </span>
              <div class="sky-evals__facts">
                <span>{e.run_count} {e.run_count === 1 ? 'run' : 'runs'}</span>
                {#if recent.length}<VerdictSparkline verdicts={recent} />{/if}
                <span class="sky-evals__pass" title="Pass rate of scored runs">{e.pass_rate_display}</span>
                <span class="sky-evals__when" title={e.last_run_at ?? undefined}>{formatRelativeTime(e.last_run_at)}</span>
              </div>
            </div>
            {#if e.goal && !tagValue(e.tags, 'case')}<p class="sky-evals__goal">{e.goal}</p>{/if}
            {#if e.tags.length > 0}
              <div class="sky-evals__tags">
                {#each e.tags as t (t)}
                  <EvalTag tag={t} onselect={() => setTag(t)} />
                {/each}
              </div>
            {/if}
            {#each variantLine(e) as v (v.key)}
              <span class="sky-evals__variant"><span class="sky-evals__wf">{v.wf}</span><span class="sky-evals__dim">·</span><span>{v.model}</span><span class="sky-evals__dim" aria-hidden="true">→</span><span class="sky-evals__strong">{v.pass}</span></span>
            {/each}
          </div>
        </li>
      {/each}
    </ul>
    {#if pageCount > 1 || rangeSummary}
      <Pagination {page} {pageCount} summary={rangeSummary} aria-label="Evals pages" onPageChange={(p) => router.setQuery({ page: p > 1 ? String(p) : null }, { push: true })} />
    {/if}
  {/if}
</section>

<style>
  .sky-evals__search {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    width: 100%;
    max-width: 22rem;
    height: var(--sky-size-control-md);
    box-sizing: border-box;
    padding: 0 var(--ds-space-3);
    border-radius: var(--sky-radius-control);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-bg);
    color: var(--ds-color-text-subtle);
  }
  .sky-evals__search:focus-within {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-evals__search input {
    flex-grow: 1;
    min-width: 0;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--ds-color-fg);
    font: inherit;
    font-size: var(--ds-text-sm);
  }
  .sky-evals__search input::placeholder {
    color: var(--ds-color-text-subtle);
  }
  .sky-evals__panel {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-card-lg);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
  }
  .sky-evals__wait {
    margin: 0;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-evals__all {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3-5);
    min-width: 0;
  }
  .sky-evals__all-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-2-5) var(--ds-space-4);
  }
  .sky-evals__all-title {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--ds-space-1) var(--ds-space-3);
  }
  .sky-evals__all-title h2 {
    margin: 0;
    font-size: var(--ds-text-xl);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
  }
  .sky-evals__all-title span,
  .sky-evals__tagged {
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-evals__tagged {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-evals__list {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    margin: 0;
    padding: var(--ds-space-1);
    list-style: none;
    border-radius: var(--sky-radius-card-lg);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-evals__row {
    display: flex;
    align-items: flex-start;
    gap: var(--ds-space-3);
    padding: var(--ds-space-3-5) var(--ds-space-2-5);
    border-radius: var(--sky-radius-row);
  }
  .sky-evals__row:hover {
    background: var(--sky-color-control-hover);
  }
  .sky-evals__row :global(.sky-evals__block) {
    flex-shrink: 0;
    display: none;
  }
  .sky-evals__row-body {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    flex-grow: 1;
    min-width: 0;
  }
  .sky-evals__row-top {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--ds-space-1-5) var(--ds-space-5);
  }
  .sky-evals__name {
    min-width: 0;
    font-size: var(--ds-text-md);
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
    text-decoration: none;
    overflow-wrap: anywhere;
  }
  .sky-evals__title {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1) var(--ds-space-2);
    min-width: 0;
  }
  .sky-evals__archived {
    display: inline-flex;
    align-items: center;
    height: 1.25rem;
    padding: 0 var(--ds-space-2);
    border-radius: var(--ds-radius-full);
    background: var(--sky-color-neutral-soft);
    color: var(--ds-color-text-muted);
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-evals__name:hover {
    color: var(--ds-color-accent-hover);
  }
  .sky-evals__name:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
    border-radius: var(--ds-radius-xs);
  }
  .sky-evals__facts {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2) var(--ds-space-3-5);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
    font-variant-numeric: tabular-nums;
  }
  .sky-evals__pass {
    color: var(--ds-color-fg);
  }
  .sky-evals__goal {
    margin: 0;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
    overflow-wrap: anywhere;
  }
  .sky-evals__tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-1-5);
    min-width: 0;
  }
  .sky-evals__variant {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1) var(--ds-space-2);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-evals__wf {
    overflow-wrap: anywhere;
  }
  .sky-evals__dim {
    color: var(--ds-color-text-subtle);
  }
  .sky-evals__strong {
    color: var(--ds-color-fg);
  }
  @media (min-width: 48rem) {
    .sky-evals__row {
      gap: var(--ds-space-4);
      padding: var(--ds-space-4) var(--ds-space-3-5);
    }
    .sky-evals__row :global(.sky-evals__block) {
      display: block;
    }
    .sky-evals__facts .sky-evals__pass {
      min-width: 4.75rem;
      text-align: right;
    }
    .sky-evals__when {
      min-width: 3.4rem;
      text-align: right;
    }
  }
</style>
