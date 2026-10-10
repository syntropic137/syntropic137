<!--
  Artifacts (boards: Artifacts, PhoneArtifacts). One responsive page: base
  styles are the phone board. Cards view groups files by the run that made
  them; List view is the table. Filters live in the URL (?type=, ?q=,
  ?view=, ?page=) so a link reproduces the view.
-->
<script lang="ts">
  import { formatBytes, formatInteger, formatRelativeTime, shortId } from '@syn137/skyline-core/format'
  import { Button, Callout, EmptyState, Input, Pagination, Skeleton, ToggleGroup } from '@syn137/skyline-svelte-v5'
  import { PageHeader } from '@syn137/skyline-svelte-v5/patterns'
  import { artifactGlyph, artifactName, groupArtifactsByRun, groupFileCount } from '@syn137/skyline-core/screens/artifacts'
  import { ApiError, countArtifactsByExecution, listArtifacts } from '@syn137/syn-ui-data'
  import type { ArtifactSummary } from '@syn137/syn-ui-data/types'
  import { isArtifactEvent, isRunEvent } from '@syn137/syn-ui-data/live'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import { href, router } from '../../lib/router'
  import type { PageProps } from '../../lib/routes'

  let { params: _params }: PageProps = $props()
  setPage({ title: 'Artifacts', crumbs: [{ label: 'Artifacts' }] })

  const PAGE_SIZE = 50
  const type = $derived(router.query.get('type') ?? 'all')
  const view = $derived(router.query.get('view') === 'list' ? 'list' : 'grid')
  const page = $derived(Math.max(1, Number(router.query.get('page')) || 1))
  const q = $derived(router.query.get('q') ?? '')

  let search = $state(router.query.get('q') ?? '')
  $effect(() => {
    const next = search.trim()
    if (next === q) return
    const t = setTimeout(() => router.setQuery({ q: next || null, page: null }), 250)
    return () => clearTimeout(t)
  })

  const list = resource(
    (signal) => listArtifacts({ page, page_size: PAGE_SIZE, q: q || undefined }, { artifact_type: type === 'all' ? undefined : type }, signal),
    { live: (t) => isArtifactEvent(t) || isRunEvent(t) },
  )

  const rows = $derived(list.data?.artifacts ?? [])
  const total = $derived(list.data?.total ?? 0)
  const pageCount = $derived(Math.max(1, Math.ceil(total / PAGE_SIZE)))
  const pageBytes = $derived(rows.reduce((n, a) => n + (a.size_bytes ?? 0), 0))

  /** Type facets, busiest first. The counts describe the whole filtered set, not the page. */
  const facets = $derived(
    Object.entries(list.data?.type_counts ?? {})
      .filter(([, n]) => n > 0)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])),
  )
  const facetTotal = $derived(facets.reduce((n, [, c]) => n + c, 0))
  const facetLabel = $derived(facets.map(([t, n]) => `${n} ${t}`).join(', '))

  const chips = $derived([
    { value: 'all', label: 'All', count: facetTotal || total },
    ...facets.map(([t, n]) => ({ value: t, label: t, count: n })),
    ...(type !== 'all' && !facets.some(([t]) => t === type) ? [{ value: type, label: type, count: 0 }] : []),
  ])

  /** Series colour slot (1-4) for a type: stable per family, never a literal colour. */
  function tone(t: string): 1 | 2 | 3 | 4 {
    if (/research|summary|markdown|doc/.test(t)) return 1
    if (/report|review/.test(t)) return 2
    if (/code|patch|diff/.test(t)) return 3
    return 4
  }

  /** The API row carries execution_id; the hand-written summary type does not declare it yet. */
  function execOf(a: ArtifactSummary): string | null {
    return 'execution_id' in a && typeof a.execution_id === 'string' ? a.execution_id : null
  }

  const groups = $derived(groupArtifactsByRun(rows.map((a) => ({ ...a, execution_id: execOf(a) }))))

  // Each run group counts the run (API total under the same filter), not its share of this page.
  const runTotals = resource((signal) => {
    const ids = groups.flatMap((g) => (g.exec ? [g.exec] : []))
    const query = { q: q || undefined }
    const scope = { artifact_type: type === 'all' ? undefined : type }
    return ids.length ? countArtifactsByExecution(ids, query, scope, signal) : Promise.resolve({} as Record<string, number>)
  })

  const titleOf = (a: ArtifactSummary) => a.title || shortId(a.id)
  const artifactHref = (a: ArtifactSummary) => href(`/artifacts/${encodeURIComponent(a.id)}`)
  const filtered = $derived(type !== 'all' || q !== '')

  function errorText(e: unknown): string {
    if (e instanceof ApiError) return typeof e.detail === 'string' ? e.detail : `The server answered ${e.status}.`
    return e instanceof Error ? e.message : String(e)
  }

  function clearFilters() {
    search = ''
    router.setQuery({ type: null, q: null, page: null })
  }

  const runCount = $derived(groups.filter((g) => g.exec).length)
  const summary = $derived(
    rows.length
      ? `${formatInteger((page - 1) * PAGE_SIZE + 1)}-${formatInteger((page - 1) * PAGE_SIZE + rows.length)} of ${formatInteger(total)} artifacts${runCount ? ` from ${formatInteger(runCount)} ${runCount === 1 ? 'execution' : 'executions'}` : ''}`
      : '',
  )
</script>

{#snippet glyph(kind: 'doc' | 'code' | 'data')}
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
    {#if kind === 'code'}<path d="M5.5 4.5L2 8l3.5 3.5M10.5 4.5L14 8l-3.5 3.5"></path>
    {:else if kind === 'data'}<ellipse cx="8" cy="3.75" rx="5" ry="1.75"></ellipse><path d="M3 3.75v8.5c0 .97 2.24 1.75 5 1.75s5-.78 5-1.75v-8.5M3 8c0 .97 2.24 1.75 5 1.75S13 8.97 13 8"></path>
    {:else}<path d="M4 1.75h5l3 3v9.5H4zM9 1.75v3h3M6 8h4M6 10.75h4"></path>{/if}
  </svg>
{/snippet}

<div class="sky-arts">
  <PageHeader
    kind="artifact"
    title="Artifacts"
    description={list.data
      ? `Everything phases wrote to artifacts/output, grouped by the run that made it. ${formatInteger(total)} ${total === 1 ? 'file' : 'files'}${rows.length ? `, ${formatBytes(pageBytes)} on this page` : ''}.`
      : 'Everything phases wrote to artifacts/output, grouped by the run that made it.'}
  >
    {#snippet actions()}
    {#if facets.length}
      <div class="sky-arts__mix">
        <div class="sky-arts__bar" role="img" aria-label={facetLabel}>
          {#each facets as [t, n] (t)}<span data-tone={tone(t)} style:flex-grow={n}></span>{/each}
        </div>
        <dl class="sky-arts__facets">
          {#each facets.slice(0, 4) as [t, n] (t)}
            <div>
              <dt><span class="sky-arts__dot" data-tone={tone(t)}></span>{t}</dt>
              <dd>{formatInteger(n)}</dd>
            </div>
          {/each}
        </dl>
      </div>
    {/if}
    {/snippet}
  </PageHeader>

  <div class="sky-arts__toolbar">
    <ToggleGroup
      class="sky-arts__chips"
      type="single"
      variant="chips"
      aria-label="Artifact type"
      items={chips}
      value={[type]}
      onValueChange={(v) => router.setQuery({ type: v[0] && v[0] !== 'all' ? v[0] : null, page: null })}
    />
    <div class="sky-arts__tools">
      <div class="sky-arts__search">
        <Input type="search" aria-label="Search artifacts" placeholder="File name, phase or session" bind:value={search} />
      </div>
      <div class="sky-arts__layout">
      <ToggleGroup
        type="single"
        variant="segmented"
        aria-label="Layout"
        items={[
          { value: 'grid', label: 'Cards' },
          { value: 'list', label: 'List' },
        ]}
        value={[view]}
        onValueChange={(v) => router.setQuery({ view: v[0] === 'list' ? 'list' : null })}
      />
      </div>
    </div>
  </div>

  {#if list.error && !list.data}
    <Callout tone="danger" title="Artifacts did not load." role="alert">
      {errorText(list.error)}
      {#snippet action()}<Button size="sm" onclick={() => list.refresh()}>Retry</Button>{/snippet}
    </Callout>
  {:else if !list.data}
    <div class="sky-arts__cards" aria-busy="true">
      <Skeleton label="Loading artifacts" variant="block" height="9rem" />
      <Skeleton variant="block" height="9rem" />
      <Skeleton variant="block" height="9rem" />
    </div>
  {:else if rows.length === 0}
    <EmptyState
      title={filtered ? 'No matching artifacts' : 'No artifacts yet'}
      description={filtered ? 'Nothing matches these filters.' : 'Files a phase writes to artifacts/output show up here when the phase completes.'}
    >
      {#snippet action()}
        {#if filtered}<Button onclick={clearFilters}>Clear filters</Button>{/if}
      {/snippet}
    </EmptyState>
  {:else}
    {#if list.error}
      <Callout tone="warning" title="Not updating.">Showing the last list that loaded. {errorText(list.error)}</Callout>
    {/if}
    {#if view === 'grid'}
      <div class="sky-arts__groups" aria-busy={list.loading}>
        {#each groups as g (g.key)}
          <section class="sky-arts__group" aria-label={g.exec ? `${g.workflow}, exec-${shortId(g.exec)}` : g.workflow}>
            <div class="sky-arts__group-head">
              {#if g.exec}
                <a class="sky-arts__group-link" href={href(`/executions/${encodeURIComponent(g.exec)}`)}>
                  <span class="sky-arts__group-name">{g.workflow}</span>
                  <span class="sky-arts__mono">exec-{shortId(g.exec)}</span>
                </a>
              {:else}
                <span class="sky-arts__group-name">{g.workflow}</span>
              {/if}
              <span class="sky-arts__mono">{groupFileCount(g.files.length, g.exec ? runTotals.data?.[g.exec] : null)}</span>
              <span class="sky-arts__rule" aria-hidden="true"></span>
              {#if g.when}<span class="sky-arts__mono">{formatRelativeTime(g.when)}</span>{/if}
            </div>
            <ul class="sky-arts__cards">
              {#each g.files as a (a.id)}
                {@const n = artifactName(a.title, null, shortId(a.id))}
                <li data-sky-row>
                  <a class="sky-arts__card" href={artifactHref(a)}>
                    <span class="sky-arts__card-top">
                      <span class="sky-arts__glyph" data-tone={tone(a.artifact_type)} aria-hidden="true">{@render glyph(artifactGlyph(a.artifact_type, n.path))}</span>
                      <span class="sky-arts__card-titles">
                        <span class="sky-arts__card-title" title={a.title ?? undefined}>{n.name}</span>
                        <span class="sky-arts__mono">{n.path ?? a.phase_id ?? 'no phase'}</span>
                      </span>
                    </span>
                    <span class="sky-arts__card-meta">
                      <span class="sky-arts__type" data-tone={tone(a.artifact_type)}><span class="sky-arts__dot" data-tone={tone(a.artifact_type)}></span>{a.artifact_type}</span>
                      <span>{formatBytes(a.size_bytes)}</span>
                      {#if n.path && a.phase_id}<span class="sky-arts__card-n">{a.phase_id}</span>{/if}
                    </span>
                  </a>
                </li>
              {/each}
            </ul>
          </section>
        {/each}
      </div>
    {:else}
      <section class="sky-arts__table" aria-label="Artifact list" aria-busy={list.loading}>
        <div class="sky-arts__thead" aria-hidden="true">
          <span></span><span>File</span><span>Type</span><span>Execution · phase</span><span class="sky-arts__num">Size</span><span class="sky-arts__num">Made ↓</span>
        </div>
        <ul class="sky-arts__rows">
          {#each rows as a (a.id)}
            {@const exec = execOf(a)}
            <li data-sky-row>
              <a class="sky-arts__row" href={artifactHref(a)}>
                <span class="sky-arts__glyph" data-tone={tone(a.artifact_type)} aria-hidden="true">{@render glyph(artifactGlyph(a.artifact_type))}</span>
                <span class="sky-arts__cell-main">
                  <span class="sky-arts__card-title">{titleOf(a)}</span>
                  <span class="sky-arts__mono">{shortId(a.id)}</span>
                </span>
                <span class="sky-arts__type sky-arts__cell-wide"><span class="sky-arts__dot" data-tone={tone(a.artifact_type)}></span>{a.artifact_type}</span>
                <span class="sky-arts__cell-main sky-arts__cell-wide">
                  <span>{a.workflow_id ?? '—'}</span>
                  <span class="sky-arts__mono">{exec ? `exec-${shortId(exec)}` : '—'} · {a.phase_id ?? '—'}</span>
                </span>
                <span class="sky-arts__num sky-arts__mono">{formatBytes(a.size_bytes)}</span>
                <span class="sky-arts__num sky-arts__mono">{a.created_at ? formatRelativeTime(a.created_at) : '—'}</span>
              </a>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
    <Pagination {page} {pageCount} {summary} onPageChange={(p) => router.setQuery({ page: p > 1 ? String(p) : null }, { push: true })} />
  {/if}
</div>

<style>
  .sky-arts {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    min-width: 0;
  }

  /* ---- type mix in the header ---- */
  .sky-arts__mix {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    width: 100%;
    min-width: 0;
    max-width: 30rem;
  }
  .sky-arts__bar {
    display: flex;
    gap: 3px;
    height: 10px;
  }
  .sky-arts__bar > span {
    flex-basis: 0;
    border-radius: var(--ds-radius-sm);
  }
  .sky-arts__facets {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: var(--ds-space-2) var(--ds-space-4);
    margin: 0;
  }
  .sky-arts__facets div {
    display: flex;
    flex-direction: column-reverse;
    gap: var(--ds-space-0-5);
    min-width: 0;
  }
  .sky-arts__facets dt {
    display: flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    color: var(--ds-color-text-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-arts__facets dd {
    margin: 0;
    font-size: var(--ds-text-xl);
    font-weight: var(--ds-font-weight-semibold);
    font-variant-numeric: tabular-nums;
  }
  [data-tone='1'] {
    --arts-tone: var(--sky-color-data-1);
  }
  [data-tone='2'] {
    --arts-tone: var(--sky-color-data-2);
  }
  [data-tone='3'] {
    --arts-tone: var(--sky-color-data-3);
  }
  [data-tone='4'] {
    --arts-tone: var(--sky-color-data-4);
  }
  .sky-arts__bar > span,
  .sky-arts__dot {
    background: var(--arts-tone);
  }
  .sky-arts__dot {
    flex-shrink: 0;
    width: 7px;
    height: 7px;
    border-radius: 2px;
  }

  /* ---- toolbar ---- */
  .sky-arts__toolbar {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-arts__tools {
    display: flex;
    align-items: center;
    gap: var(--ds-space-3);
    min-width: 0;
    order: -1;
  }
  .sky-arts__layout {
    display: none;
  }
  .sky-arts__search {
    flex: 1 1 auto;
    min-width: 0;
  }

  /* ---- cards ---- */
  .sky-arts__groups {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-7);
  }
  .sky-arts__group {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-arts__group-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2) var(--ds-space-3);
    min-width: 0;
  }
  .sky-arts__group-link {
    display: inline-flex;
    align-items: baseline;
    gap: var(--ds-space-2);
    min-width: 0;
    color: var(--ds-color-fg);
    text-decoration: none;
  }
  .sky-arts__group-link:hover .sky-arts__group-name {
    text-decoration: underline;
  }
  .sky-arts__group-link:focus-visible,
  .sky-arts__card:focus-visible,
  .sky-arts__row:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-arts__group-name {
    font-size: var(--ds-text-lg);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
  }
  .sky-arts__rule {
    display: none;
    flex: 1 1 2rem;
    height: 1px;
    background: var(--sky-color-divider);
  }
  .sky-arts__mono {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-arts__cards {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--ds-space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-arts__card {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    height: 100%;
    box-sizing: border-box;
    padding: var(--ds-space-4);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
    color: var(--ds-color-fg);
    text-decoration: none;
  }
  .sky-arts__card:hover {
    border-color: var(--sky-color-border-hover);
    color: var(--ds-color-fg);
  }
  .sky-arts__card-top {
    display: flex;
    align-items: flex-start;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-arts__glyph {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: var(--sky-radius-control);
    background: color-mix(in oklab, var(--arts-tone) 16%, transparent);
    color: var(--arts-tone);
  }
  .sky-arts__card-titles,
  .sky-arts__cell-main {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    min-width: 0;
  }
  .sky-arts__card-title {
    font-weight: var(--ds-font-weight-semibold);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-arts__card-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2) var(--ds-space-3);
    margin-top: auto;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
  .sky-arts__card-n {
    margin-left: auto;
    color: var(--ds-color-text-subtle);
  }
  .sky-arts__type {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    color: var(--ds-color-fg);
  }

  /* ---- list ---- */
  .sky-arts__table {
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    overflow: hidden;
  }
  .sky-arts__thead {
    display: none;
  }
  .sky-arts__rows {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-arts__rows li + li {
    border-top: var(--ds-border-width) solid var(--sky-color-divider);
  }
  .sky-arts__row {
    display: grid;
    grid-template-columns: 32px minmax(0, 1fr) auto auto;
    align-items: center;
    gap: var(--ds-space-3);
    padding: var(--ds-space-3) var(--ds-space-4);
    color: var(--ds-color-fg);
    text-decoration: none;
  }
  .sky-arts__row:hover {
    background: var(--ds-color-surface-raised);
    color: var(--ds-color-fg);
  }
  .sky-arts__cell-wide {
    display: none;
  }
  .sky-arts__num {
    text-align: right;
  }

  @media (pointer: coarse) {
    .sky-arts__row {
      min-height: var(--sky-size-touch);
    }
    .sky-arts__group-link {
      min-height: var(--sky-size-touch);
      align-items: center;
    }
  }

  @media (min-width: 48rem) {
    .sky-arts__toolbar {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
    }
    .sky-arts__tools {
      order: 0;
    }
    .sky-arts__layout {
      display: block;
    }
    .sky-arts__rule {
      display: block;
    }
    .sky-arts__search {
      width: 18rem;
      flex: 0 0 auto;
    }
    .sky-arts__facets {
      grid-template-columns: repeat(4, minmax(0, auto));
      gap: var(--ds-space-4) var(--ds-space-8);
    }
    .sky-arts__cards {
      grid-template-columns: repeat(auto-fill, minmax(18rem, 1fr));
    }
    .sky-arts__thead,
    .sky-arts__row {
      display: grid;
      grid-template-columns: 32px minmax(0, 2fr) minmax(0, 1fr) minmax(0, 1.6fr) 5rem 6rem;
      gap: var(--ds-space-4);
    }
    .sky-arts__thead {
      align-items: center;
      padding: var(--ds-space-2-5) var(--ds-space-4);
      border-bottom: var(--ds-border-width) solid var(--ds-color-border);
      font-family: var(--ds-font-mono);
      font-size: var(--sky-text-label);
      letter-spacing: var(--sky-tracking-label);
      text-transform: uppercase;
      color: var(--ds-color-text-subtle);
    }
    .sky-arts__cell-wide {
      display: flex;
    }
  }
</style>
