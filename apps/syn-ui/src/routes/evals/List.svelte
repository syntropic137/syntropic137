<!-- Evals list. Boards: Evals · PhoneEvals. Verdict board over every eval, then the tag-filterable list. -->
<script lang="ts">
  import { listEvalRuns, listEvals, mapLimit, MAX_PAGE_SIZE } from '@syn137/syn-ui-data'
  import type { EvalSummary, EvalVerdict } from '@syn137/syn-ui-data'
  import { Callout, EmptyState, Pagination, Skeleton } from '@syn137/skyline-svelte-v5'
  import { PageHeader, VerdictBlock, VerdictBoard, VerdictSparkline } from '@syn137/skyline-svelte-v5/patterns'
  import { formatDate, formatRelativeTime } from '@syn137/skyline-core/format'
  import { cellKey, normalizeVerdict } from '@syn137/skyline-core/patterns'
  import { buildEvalBoard, sortEvalsByLastRun, tagValue, withLatestRun } from '@syn137/skyline-core/screens/evals'
  import { isRunFinished } from '@syn137/syn-ui-data/live'
  import { resource } from '../../lib/load.svelte'
  import { href, router } from '../../lib/router'
  import type { PageProps } from '../../lib/routes'
  import EvalTag from './EvalTag.svelte'
  import FlaskIcon from './FlaskIcon.svelte'

  let { params: _params }: PageProps = $props()

  const PAGE_SIZE = 20
  const SPARK_RUNS = 8

  const tag = $derived(router.query.get('tag') ?? '')
  const page = $derived.by(() => {
    const n = Number(router.query.get('page') ?? '1')
    return Number.isInteger(n) && n > 0 ? n : 1
  })

  // Every eval feeds the board; the list below follows the tag filter and page.
  const all = resource((signal) => listEvals({ page_size: MAX_PAGE_SIZE }, signal), { live: isRunFinished })
  const list = resource(
    async (signal) => {
      const t = tag
      const p = page
      const res = await listEvals({ tag: t || undefined, page: p, page_size: PAGE_SIZE }, signal)
      const rows = sortEvalsByLastRun(res.evals)
      // TODO(#624): N+1 for sparklines, as in the React list. Ask the API for recent verdicts on EvalResponse.
      const recent = await mapLimit(rows, 4, async (e): Promise<(EvalVerdict | null)[]> => {
        if (e.run_count === 0) return []
        try {
          const runs = await listEvalRuns(e.eval_id, { page_size: SPARK_RUNS }, signal)
          return runs.items.map((r) => r.verdict).reverse()
        } catch {
          return [e.last_verdict ?? null]
        }
      })
      return { ...res, rows: rows.map((e, i) => ({ eval: e, recent: recent[i] ?? [] })) }
    },
    { live: isRunFinished },
  )

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

  // The readout shows the latest run of the selected eval: evidence, duration, links.
  const pickRun = resource((signal) => {
    const id = pickEvalId
    return id ? listEvalRuns(id, { page_size: 1 }, signal) : Promise.resolve(null)
  })

  const cells = $derived.by(() => {
    if (!pickKey) return board.cells
    const run = pickRun.data?.items[0]
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
  const pageCount = $derived(list.data ? Math.max(1, Math.ceil(list.data.total / PAGE_SIZE)) : 1)
  const rangeSummary = $derived.by(() => {
    if (!list.data || list.data.total === 0) return ''
    const from = (page - 1) * PAGE_SIZE + 1
    const to = Math.min(list.data.total, from + list.data.rows.length - 1)
    return `Showing ${from}–${to} of ${list.data.total} evals`
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
    <input type="search" aria-label="Filter evals by tag" placeholder="Filter by tag, e.g. case:codex-cost-limit" bind:value={search} />
  </form>
</PageHeader>

{#if all.error && !all.data}
  <Callout tone="danger" title="Could not load evals">{all.error instanceof Error ? all.error.message : String(all.error)}</Callout>
{:else if !all.data}
  <section class="sky-evals__panel" aria-busy="true" aria-label="Loading verdict board">
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
      <span>Newest run first. Select a tag to filter.</span>
    </div>
    {#if tag}
      <div class="sky-evals__tagged">
        <span>Tagged</span>
        <EvalTag {tag} removable onremove={() => setTag(null)} />
      </div>
    {/if}
  </div>

  {#if list.error && !list.data}
    <Callout tone="danger" title="Could not load evals">{list.error instanceof Error ? list.error.message : String(list.error)}</Callout>
  {:else if !list.data}
    <div class="sky-evals__list" aria-busy="true" aria-label="Loading evals">
      {#each [0, 1, 2, 3] as i (i)}
        <div class="sky-evals__row"><Skeleton variant="block" width="2.75rem" height="2.4rem" /><div class="sky-evals__row-body"><Skeleton variant="text" lines={3} /></div></div>
      {/each}
    </div>
  {:else if list.data.rows.length === 0}
    <div class="sky-evals__list">
      {#if list.data.total > 0}
        <EmptyState title="No evals on this page" description={`There are ${list.data.total} evals.`}>
          {#snippet icon()}<FlaskIcon />{/snippet}
          {#snippet action()}<a href={href(tag ? `/evals?tag=${encodeURIComponent(tag)}` : '/evals')}>Back to page 1</a>{/snippet}
        </EmptyState>
      {:else}
        <EmptyState
          title={tag ? `No evals tagged ${tag}` : 'No evals yet'}
          description="Create one with scripts/eval_suite.py launch, or POST /evals with a goal and a pinned baseline repo. Each execution launched into it becomes a run here."
        >
          {#snippet icon()}<FlaskIcon />{/snippet}
        </EmptyState>
      {/if}
    </div>
  {:else}
    <ul class="sky-evals__list" aria-busy={list.loading}>
      {#each list.data.rows as row (row.eval.eval_id)}
        {@const e = row.eval}
        {@const verdict = e.run_count > 0 ? normalizeVerdict(e.last_verdict) : 'unscored'}
        <li class="sky-evals__row">
          <VerdictBlock class="sky-evals__block" {verdict} size={44} />
          <div class="sky-evals__row-body">
            <div class="sky-evals__row-top">
              <a class="sky-evals__name" href={href(`/evals/${encodeURIComponent(e.eval_id)}`)}>{e.name}</a>
              <div class="sky-evals__facts">
                <span>{e.run_count} {e.run_count === 1 ? 'run' : 'runs'}</span>
                <VerdictSparkline verdicts={(row.recent.length ? row.recent : [e.last_verdict ?? null]).map((v) => normalizeVerdict(v))} />
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
