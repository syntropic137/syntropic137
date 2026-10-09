<!--
  Overview (/). Boards: Main (desktop) and PhoneOverview. One responsive
  page, base styles are the phone layout.

  Data: metrics (totals, outcome counts, token mix), the contribution heatmap
  (Skyline days), the newest executions (Recent runs, attention chips,
  running count), workflows (count, most-run) and triggers (count, repos).
  Metrics and runs refetch on workflow and phase events; git events from the
  activity stream feed Live commits, seeded from GET /events/recent
  (event_type=git_commit) as the React Overview does.
-->
<script lang="ts">
  import { formatCost, formatInteger, formatRelativeTime, formatTokens } from '@syn137/skyline-core/format'
  import { dayFromMs, type SkylineDay } from '@syn137/skyline-core/geometry'
  import { outcomeStatus, runBarPercent, runSegments, runSlots, runSubline } from '@syn137/skyline-core/patterns'
  import {
    activeDayCount,
    attentionRuns,
    combineCommits,
    distinctRepoCount,
    heatmapToSkylineDays,
    mergeLiveCommits,
    outcomeCounts,
    outcomeLine,
    overviewHeadline,
    recentCommits,
    runningCount,
    skylineYears,
    toLiveCommit,
    tokenMix,
    topWorkflows,
    triggerLine,
    type LiveCommit,
    OUTCOME_RANGES,
    OUTCOME_RANGE_STORAGE_KEY,
    outcomeRangeNoun,
    outcomeRangeStart,
    parseOutcomeRange,
    type OutcomeRange,
  } from '@syn137/skyline-core/screens/overview'
  import { evalBadge } from '@syn137/skyline-core/screens/executions'
  import { Button, Callout, EmptyState, Skeleton, ToggleGroup } from '@syn137/skyline-svelte-v5'
  import { OutcomeRing, RunRow, Skyline, StatusBadge } from '@syn137/skyline-svelte-v5/patterns'
  import { getContributionHeatmap, getMetrics, listExecutions, listRecentEvents, listTriggers, listWorkflows } from '@syn137/syn-ui-data'
  import { isGitEvent, isRunEvent, isRunFinished, subscribeActivity } from '@syn137/syn-ui-data/live'
  import { live } from '../../lib/live.svelte'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import type { PageProps } from '../../lib/routes'
  import { href } from '../../lib/router'
  import LiveCommits from './parts/LiveCommits.svelte'
  import Pipeline from './parts/Pipeline.svelte'
  import TokenMix from './parts/TokenMix.svelte'
  import TopWorkflows from './parts/TopWorkflows.svelte'
  import type { PipelineItem } from './parts/types'
  import { readViewer, writeViewer } from './parts/viewerStore'

  let { params: _params }: PageProps = $props()

  setPage({ title: 'Overview', crumbs: [] })

  const today = dayFromMs(Date.now())
  const thisYear = Number(today.slice(0, 4))
  const RECENT = 6

  const metrics = resource((signal) => getMetrics(undefined, signal), { live: isRunEvent })
  const runs = resource((signal) => listExecutions({ page: 1, page_size: RECENT }, signal), { live: isRunEvent })
  const heatmap = resource((signal) => getContributionHeatmap({ start_date: `${thisYear - 1}-01-01`, end_date: today }, signal), {
    live: isRunFinished,
    liveIntervalMs: 15_000,
  })
  const workflows = resource((signal) => listWorkflows({ page_size: 100 }, signal))
  const triggers = resource((signal) => listTriggers({}, signal))

  // ---- derived view data ----
  const days = $derived<SkylineDay[]>(heatmapToSkylineDays(heatmap.data?.days))
  const years = $derived(skylineYears(days, thisYear))
  let year = $state(thisYear)
  let selectedDay = $state<string | null>(null)
  const yearDays = $derived(days.filter((d) => d.date.startsWith(String(year))))

  const rows = $derived(runs.data?.executions ?? [])
  const attention = $derived(attentionRuns(rows))
  const headline = $derived(overviewHeadline({ running: runningCount(rows), needsLook: attention.length }))
  const outcomes = $derived(outcomeCounts(metrics.data?.execution_status_counts))
  const executionsTotal = $derived(runs.data?.total ?? metrics.data?.total_workflows ?? 0)
  const mix = $derived(tokenMix(metrics.data))

  // ---- Outcomes range (feedback 9587ce0c): /metrics has no time window, so a
  // ranged view reads /executions' status_counts with started_after. ----
  let outcomeRange = $state<OutcomeRange>(parseOutcomeRange(readViewer(OUTCOME_RANGE_STORAGE_KEY)))
  const rangedRuns = resource(
    (signal) => {
      const after = outcomeRangeStart(outcomeRange, Date.now())
      return after ? listExecutions({ page: 1, page_size: 1, started_after: after }, signal) : Promise.resolve(null)
    },
    { live: isRunEvent },
  )
  const rangedOutcomes = $derived(outcomeRange === 'all' ? (metrics.data ? outcomes : null) : rangedRuns.data ? outcomeCounts(rangedRuns.data.status_counts) : null)
  function onOutcomeRange(v: string | undefined) {
    outcomeRange = parseOutcomeRange(v)
    writeViewer(OUTCOME_RANGE_STORAGE_KEY, outcomeRange === 'all' ? null : outcomeRange)
  }
  const top = $derived(topWorkflows(workflows.data?.workflows))
  const longest = $derived(Math.max(0, ...rows.map((r) => (r.duration_seconds ?? 0) * 1000)))
  const slots = $derived(runSlots(rows.map((r) => r.phase_progress?.possible ?? r.total_phases)))

  const stats = $derived([
    { label: 'Sessions', value: formatInteger(metrics.data?.total_sessions) },
    { label: 'Active days', value: heatmap.data ? formatInteger(activeDayCount(yearDays.length ? yearDays : days)) : '…' },
    { label: 'Tokens', value: formatTokens(metrics.data?.total_tokens) },
    { label: 'Spend', value: formatCost(metrics.data?.total_cost_usd) },
  ])

  const pipeline = $derived.by((): PipelineItem[] => {
    const m = metrics.data
    const repos = distinctRepoCount(triggers.data?.triggers)
    const count = (n: number | null | undefined) => (n === null || n === undefined ? '…' : formatInteger(n))
    return [
      { kind: 'trigger', label: 'Triggers', count: count(triggers.data?.total), sub: triggerLine(repos), subShort: triggerLine(repos, true), path: '/triggers' },
      { kind: 'workflow', label: 'Workflows', count: count(workflows.data?.total), sub: 'phased definitions, ready to run', subShort: 'phased definitions', path: '/workflows' },
      { kind: 'execution', label: 'Executions', count: count(executionsTotal), sub: outcomeLine(outcomes), subShort: outcomeLine(outcomes, true), path: '/executions' },
      { kind: 'session', label: 'Sessions', count: count(m?.total_sessions), sub: 'one agent working one phase', subShort: 'one agent, one phase', path: '/sessions' },
      { kind: 'artifact', label: 'Artifacts', count: count(m?.total_artifacts), sub: 'files the phases left behind', subShort: 'files the phases left behind', path: '/artifacts' },
    ]
  })

  const isEmpty = $derived(!!metrics.data && !!runs.data && runs.data.total === 0 && metrics.data.total_sessions === 0)
  const firstLoad = $derived(!metrics.data && !metrics.error)

  // ---- live commits: the latest from the API, then the activity stream ahead of them ----
  const recent = resource((signal) => listRecentEvents({ event_type: 'git_commit', limit: 30 }, signal))
  let liveCommits = $state<LiveCommit[]>([])
  const commits = $derived(combineCommits(liveCommits, recentCommits(recent.data?.events)))
  $effect(() =>
    subscribeActivity({
      filter: isGitEvent,
      onFrames: (frames) => {
        const incoming = frames.map(toLiveCommit).filter((c): c is LiveCommit => c !== null)
        if (incoming.length) liveCommits = mergeLiveCommits(liveCommits, incoming)
      },
    }),
  )

  function retry() {
    metrics.refresh()
    runs.refresh()
    heatmap.refresh()
    workflows.refresh()
    triggers.refresh()
    recent.refresh()
  }

  const execHref = (id: string) => href(`/executions/${encodeURIComponent(id)}`)
  const dayRunsHref = (d: SkylineDay) => href(`/executions?day=${d.date}`)

  function onYear(y: number) {
    year = y
    selectedDay = null
  }
</script>

<div class="sky-ov">
  {#if metrics.error && !metrics.data}
    <Callout tone="danger" title="The overview did not load">
      {metrics.error instanceof Error ? metrics.error.message : 'The API did not answer.'}
      {#snippet action()}<Button variant="outline" size="sm" onclick={retry}>Try again</Button>{/snippet}
    </Callout>
  {/if}

  <section class="sky-ov-hero" aria-label="Right now">
    <div class="sky-ov-hero__top">
      <div class="sky-ov-hero__lead">
        <div class="sky-ov-eyebrow"><span class="sky-ov-eyebrow__dot" data-state={live.state}></span>Right now</div>
        {#if firstLoad}
          <Skeleton variant="title" width="14ch" label="Loading overview" />
          <Skeleton variant="text" width="20ch" />
        {:else}
          <h1>{headline.lead}<br /><span>{headline.follow}</span></h1>
        {/if}
        {#if attention.length}
          <ul class="sky-ov-chips" aria-label="Runs that need a look">
            {#each attention as r (r.workflow_execution_id)}
              <li>
                <a class="sky-ov-chip" href={execHref(r.workflow_execution_id)}>
                  <StatusBadge status={outcomeStatus(r.status, r.failure_classification)} shape="glyph" />
                  <span class="sky-ov-chip__name">{r.workflow_name}</span>
                  <span class="sky-ov-chip__meta">
                    <span class="sky-ov-chip__verb">failed in </span>{r.duration_display || '—'} · {formatRelativeTime(r.started_at)}
                  </span>
                </a>
              </li>
            {/each}
          </ul>
        {/if}
      </div>

      <dl class="sky-ov-stats">
        {#each stats as s (s.label)}
          <div>
            <dt>{s.label}</dt>
            <dd>
              {#if firstLoad}<Skeleton variant="text" width="4ch" />{:else}{s.value}{/if}
            </dd>
          </div>
        {/each}
      </dl>
    </div>

    <div class="sky-ov-hero__chart">
      {#if heatmap.error && !heatmap.data}
        <Callout tone="warning" title="Activity did not load">
          The Skyline needs the contribution heatmap.
          {#snippet action()}<Button variant="outline" size="sm" onclick={() => heatmap.refresh()}>Retry</Button>{/snippet}
        </Callout>
      {:else if !heatmap.data}
        <Skeleton variant="block" height="11rem" label="Loading activity" />
      {:else if days.length === 0}
        <EmptyState title="No activity yet" description="Each day an agent works becomes a bar here." level={3} bare />
      {:else}
        <Skyline days={yearDays} {today} {year} {years} onyearchange={onYear} bind:selected={selectedDay} runsHref={dayRunsHref} />
      {/if}
    </div>
  </section>

  {#if isEmpty}
    <EmptyState title="No runs yet" description="Run your first workflow and it shows up here, from trigger to artifact.">
      {#snippet action()}<code class="sky-ov-cmd">syn run workflow.yaml</code>{/snippet}
    </EmptyState>
  {/if}

  <Pipeline items={pipeline} />

  <div class="sky-ov-split">
    <section class="sky-ov-runs" aria-labelledby="sky-ov-runs-title">
      <div class="sky-ov-section-head">
        <div>
          <h2 id="sky-ov-runs-title">Recent runs</h2>
          <p>Each block is a phase; the line under it is duration.</p>
        </div>
        <a class="sky-ov-more" href={href('/executions')}>{runs.data ? `View all ${formatInteger(runs.data.total)} →` : 'View all →'}</a>
      </div>
      {#if runs.error && !runs.data}
        <Callout tone="danger" title="Runs did not load">
          {runs.error instanceof Error ? runs.error.message : 'The API did not answer.'}
          {#snippet action()}<Button variant="outline" size="sm" onclick={() => runs.refresh()}>Retry</Button>{/snippet}
        </Callout>
      {:else if !runs.data}
        <Skeleton variant="block" height="3.5rem" />
        <Skeleton variant="block" height="3.5rem" />
        <Skeleton variant="block" height="3.5rem" />
      {:else if rows.length === 0}
        <EmptyState title="No runs yet" description="Executions appear here as soon as a workflow starts." level={3} />
      {:else}
        <div class="sky-ov-runs__list">
          {#each rows as r (r.workflow_execution_id)}
            <RunRow
              status={outcomeStatus(r.status, r.failure_classification)}
              name={r.workflow_name}
              tag={evalBadge(r.eval)}
              sub={runSubline(r.repos_display ?? r.repos?.[0] ?? null, r.phase_progress?.completed ?? r.completed_phases, r.phase_progress?.possible ?? r.total_phases)}
              href={execHref(r.workflow_execution_id)}
              segments={runSegments({ status: r.status, done: r.phase_progress?.completed ?? r.completed_phases, total: r.phase_progress?.possible ?? r.total_phases })}
              barPercent={runBarPercent((r.duration_seconds ?? 0) * 1000, longest)}
              {slots}
              duration={r.duration_display || '—'}
              tokens={r.total_tokens_display}
              cost={r.total_cost_display}
              when={formatRelativeTime(r.started_at)}
            />
          {/each}
        </div>
      {/if}
      <LiveCommits {commits} state={live.state} loading={!recent.data && !recent.error} />
    </section>

    <div class="sky-ov-side">
      <section class="sky-ov-card sky-ov-outcomes" aria-label="Outcomes">
        <ToggleGroup
          class="sky-ov-outcomes__range"
          type="single"
          variant="segmented"
          size="sm"
          mono
          aria-label="Outcomes range"
          items={OUTCOME_RANGES.map((r) => ({ value: r.value, label: r.label }))}
          value={[outcomeRange]}
          onValueChange={(v) => onOutcomeRange(v[0])}
        />
        {#if rangedOutcomes}
          <OutcomeRing completed={rangedOutcomes.completed} failed={rangedOutcomes.failed} cancelled={rangedOutcomes.cancelled} noun={outcomeRangeNoun(outcomeRange)} />
        {:else if outcomeRange !== 'all' && rangedRuns.error}
          <Callout tone="warning" title="Outcomes for this range did not load">
            {#snippet action()}<Button variant="outline" size="sm" onclick={() => rangedRuns.refresh()}>Retry</Button>{/snippet}
          </Callout>
        {:else}
          <Skeleton variant="block" height="7.5rem" label="Loading outcomes" />
        {/if}
      </section>
      {#if metrics.data}
        <TokenMix total={mix.total} parts={mix.parts} />
      {:else}
        <section class="sky-ov-card"><Skeleton variant="block" height="6rem" label="Loading token mix" /></section>
      {/if}
      {#if workflows.error && !workflows.data}
        <Callout tone="warning" title="Workflows did not load">
          {#snippet action()}<Button variant="outline" size="sm" onclick={() => workflows.refresh()}>Retry</Button>{/snippet}
        </Callout>
      {:else if workflows.data}
        <TopWorkflows items={top} total={workflows.data.total} />
      {:else}
        <section class="sky-ov-card"><Skeleton variant="text" lines={5} label="Loading workflows" /></section>
      {/if}
    </div>
  </div>
</div>

<style>
  .sky-ov {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-7);
    padding-block: var(--ds-space-2) var(--ds-space-8);
  }

  /* ---- hero ---- */
  .sky-ov-hero {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    min-width: 0;
  }
  .sky-ov-hero__top {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
  }
  .sky-ov-hero__lead {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3-5);
    min-width: 0;
  }
  .sky-ov-eyebrow {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-muted);
  }
  .sky-ov-eyebrow__dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--ds-color-accent);
    box-shadow: 0 0 0 4px var(--sky-color-accent-ring);
  }
  .sky-ov-eyebrow__dot[data-state='offline'],
  .sky-ov-eyebrow__dot[data-state='connecting'] {
    background: var(--ds-color-text-subtle);
    box-shadow: 0 0 0 4px var(--sky-color-neutral-soft);
  }
  h1 {
    margin: 0;
    font-size: var(--sky-text-hero);
    line-height: var(--ds-line-height-tight);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-display);
  }
  h1 span {
    color: var(--ds-color-text-subtle);
  }
  .sky-ov-chips {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-ov-chip {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    min-height: var(--sky-size-control-md);
    padding: 0 var(--ds-space-3-5) 0 var(--ds-space-2-5);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-bg);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-fg);
    text-decoration: none;
  }
  .sky-ov-chip:hover {
    border-color: var(--sky-color-border-hover);
    color: var(--ds-color-fg);
  }
  .sky-ov-chip:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-ov-chip__name {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-ov-chip__meta {
    flex-shrink: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-ov-chip__verb {
    display: none;
  }
  .sky-ov-stats {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--ds-space-4) var(--ds-space-6);
    margin: 0;
  }
  .sky-ov-stats div {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
  }
  .sky-ov-stats dt {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-ov-stats dd {
    margin: 0;
    font-size: var(--sky-text-figure);
    line-height: var(--ds-line-height-tight);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-display);
    font-variant-numeric: tabular-nums;
  }
  .sky-ov-hero__chart {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-ov-cmd {
    padding: var(--ds-space-1) var(--ds-space-2);
    border-radius: var(--ds-radius-sm);
    background: var(--ds-color-surface-raised);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--sky-color-text-code);
  }

  /* ---- lower half ---- */
  .sky-ov-split {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-7);
  }
  .sky-ov-runs {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-ov-section-head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--ds-space-2) var(--ds-space-3);
  }
  .sky-ov-section-head > div {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--ds-space-1) var(--ds-space-3);
  }
  .sky-ov-section-head h2 {
    margin: 0;
    font-size: var(--ds-text-lg);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
  }
  .sky-ov-section-head p {
    display: none;
    margin: 0;
    font-size: var(--ds-text-md);
    color: var(--ds-color-text-muted);
  }
  .sky-ov-runs__list {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    container-type: inline-size;
  }
  .sky-ov-side {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
  }

  /* Shared by the parts in ./parts (scoped to this page). */
  .sky-ov :global(.sky-ov-outcomes__range) {
    align-self: flex-end;
  }
  .sky-ov :global(.sky-ov-card) {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-ov :global(.sky-ov-card__head) {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--ds-space-3);
  }
  .sky-ov :global(.sky-ov-card__head h2) {
    margin: 0;
    font-size: var(--sky-text-body);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-ov :global(.sky-ov-mono) {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
  .sky-ov :global(.sky-ov-mono[data-tone='fg']) {
    color: var(--ds-color-fg);
  }
  .sky-ov :global(.sky-ov-more) {
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
    text-decoration: none;
  }
  .sky-ov :global(.sky-ov-more:hover) {
    color: var(--ds-color-fg);
  }
  .sky-ov :global(.sky-ov-more:focus-visible) {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-ov-chip {
      min-height: var(--sky-size-touch);
    }
    .sky-ov :global(.sky-ov-more) {
      display: inline-flex;
      align-items: center;
      min-height: var(--sky-size-touch);
    }
  }

  /* ---- 48rem: the Main board ---- */
  @media (min-width: 48rem) {
    .sky-ov {
      gap: var(--ds-space-10);
    }
    .sky-ov-hero {
      gap: 0;
      border-radius: var(--sky-radius-2xl);
      border: var(--ds-border-width) solid var(--ds-color-border);
      background:
        radial-gradient(60% 85% at 62% 108%, var(--sky-color-hero-glow), transparent 72%),
        var(--ds-color-surface);
      box-shadow: var(--sky-shadow-raised);
      overflow: hidden;
    }
    .sky-ov-hero__top {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--ds-space-8) var(--ds-space-12);
      padding: var(--ds-space-10) var(--ds-space-10) var(--ds-space-2);
    }
    .sky-ov-hero__lead {
      gap: var(--ds-space-5);
      max-width: 35rem;
    }
    .sky-ov-chips {
      flex-direction: row;
      flex-wrap: wrap;
    }
    .sky-ov-chip__verb {
      display: inline;
    }
    .sky-ov-stats {
      grid-template-columns: repeat(2, minmax(7.5rem, auto));
      gap: var(--ds-space-6) var(--ds-space-10);
    }
    .sky-ov-stats dd {
      font-size: clamp(var(--sky-text-3xl), 1.2rem + 1.4vw, 2.375rem);
    }
    .sky-ov-hero__chart {
      padding: var(--ds-space-5) var(--ds-space-7) var(--ds-space-5);
    }
    .sky-ov-section-head h2 {
      font-size: var(--ds-text-xl);
    }
    .sky-ov-section-head p {
      display: block;
    }
    .sky-ov :global(.sky-ov-card) {
      padding: var(--ds-space-5);
    }
  }

  /* ---- 64rem: runs beside the side column ---- */
  @media (min-width: 64rem) {
    .sky-ov-split {
      flex-direction: row;
      align-items: flex-start;
      gap: var(--ds-space-12);
    }
    .sky-ov-runs {
      flex: 1 1 0;
    }
    .sky-ov-side {
      flex: 0 0 var(--sky-side-column);
      gap: var(--ds-space-5);
    }
  }
</style>
