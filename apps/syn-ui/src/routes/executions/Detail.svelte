<!--
  Execution (boards: Execution, PhoneExecution, PhaseKit, UsageMeter).
  Base styles are the phone board (Usage above the timeline); from 64rem the
  usage meter moves to a side column. Running executions refresh on their
  own event stream and on activity events.
-->
<script lang="ts">
  import { phaseTone } from '@syn137/skyline-core/geometry'
  import { formatBytes, formatCostPrecise, formatDateTime, formatDuration, formatInteger, shortId, durationBetween } from '@syn137/skyline-core/format'
  import { statusSemantics } from '@syn137/skyline-core/patterns'
  import {
    evalBadge,
    phaseProgressText,
    canCancel,
    costRowsByPhase,
    isExecutionEvent,
    phaseKit,
    phaseMeta,
    phaseModelChip,
    phaseNumber,
    phaseTokenSplit,
    phaseTokens,
    provenanceFor,
    runIdentityText,
    timelineCaption,
    usageNote,
  } from '@syn137/skyline-core/screens/executions'
  import { Button, Callout, EmptyState, Skeleton } from '@syn137/skyline-svelte-v5'
  import { CopyButton, PageHeader, PhaseBlocks, PhaseKitChips, ProvenanceStrip, RunTiles, StatusBadge, UsageMeter } from '@syn137/skyline-svelte-v5/patterns'
  import { ApiError, cancelExecution, getArtifact, getExecution, getSessionInventory } from '@syn137/syn-ui-data'
  import type { ArtifactResponse, PhaseExecutionDetail } from '@syn137/syn-ui-data/types'
  import { subscribeExecution } from '@syn137/syn-ui-data/live'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import { href } from '../../lib/router'
  import type { PageProps } from '../../lib/routes'

  let { params }: PageProps = $props()
  const id = $derived(params.executionId ?? '')

  const exec = resource((signal) => getExecution(id, signal), { live: isExecutionEvent })
  const inventory = resource((signal) => getSessionInventory(id, signal).catch(() => null))

  const artifactIds = $derived((exec.data?.artifact_ids ?? []).join(','))
  const artifacts = resource(async (signal) => {
    const ids = artifactIds ? artifactIds.split(',') : []
    // TODO(#624): one call per artifact (N+1); the execution response should carry name and size.
    const settled = await Promise.allSettled(ids.map((a) => getArtifact(a, false, signal)))
    const map = new Map<string, ArtifactResponse>()
    settled.forEach((r, i) => {
      if (r.status === 'fulfilled') map.set(ids[i]!, r.value)
    })
    return map
  })

  const live = $derived(!!exec.data && !statusSemantics(exec.data.status).terminal)

  // A running execution also listens on its own stream (throttled refetch).
  $effect(() => {
    if (!live || !id) return
    let timer: ReturnType<typeof setTimeout> | undefined
    const stop = subscribeExecution(id, {
      onFrames: () => {
        timer ??= setTimeout(() => {
          timer = undefined
          exec.refresh()
          inventory.refresh()
        }, 1500)
      },
    })
    return () => {
      clearTimeout(timer)
      stop()
    }
  })

  $effect(() => {
    const d = exec.data
    if (d)
      setPage({
        title: `${d.workflow_name} ${shortId(d.workflow_execution_id)}`,
        crumbs: [
          { label: 'Workflows', href: '/workflows' },
          { label: d.workflow_name || d.workflow_id, href: `/workflows/${d.workflow_id}` },
          { label: 'Execution', id: shortId(d.workflow_execution_id) },
        ],
      })
  })

  const d = $derived(exec.data)
  const ev = $derived(evalBadge(d?.eval))
  const phases = $derived(d?.phases ?? [])
  /** Declared phases that have not started yet (phases holds only started ones). */
  const notStarted = $derived(d ? d.phase_plan.filter((p) => !phases.some((x) => x.phase_id === p.phase_id)) : [])

  const durationText = $derived.by(() => {
    if (!d) return '—'
    const ms = durationBetween(d.started_at, d.completed_at ?? (live ? new Date().toISOString() : null))
    return formatDuration(ms)
  })

  const figures = $derived(
    d
      ? [
          { label: 'Duration', value: durationText },
          { label: 'Cost', value: formatCostPrecise(d.total_cost_usd) + (d.unpriced_observation_count ? '+' : '') },
          { label: 'Tokens', value: formatInteger(d.total_tokens) },
          { label: 'Artifacts', value: String(d.artifact_ids.length) },
        ]
      : [],
  )

  const blocks = $derived([
    ...phases.map((p) => {
      const m = phaseMeta(p)
      return { name: p.name, durationMs: p.duration_seconds === null ? null : p.duration_seconds * 1000, tokens: phaseTokens(p), tone: phaseTone(p.status), meta: m.meta, metaShort: m.metaShort }
    }),
    ...notStarted.map((p) => ({ name: p.name, durationMs: null, tokens: 0, tone: phaseTone(p.status), metaShort: p.status_display })),
  ])

  const caption = $derived(timelineCaption(phases))
  const provenance = $derived(provenanceFor(phases, inventory.data))
  const tokens = $derived(
    d ? { cacheRead: d.total_cache_read_tokens, cacheWrite: d.total_cache_creation_tokens, output: d.total_output_tokens, input: d.total_input_tokens } : null,
  )
  const failed = $derived(d?.error_message ? (d.failure_classification === 'correct_refusal' ? 'warning' : 'danger') : null)

  function artifactTile(p: PhaseExecutionDetail) {
    if (!p.artifact_id) return null
    const a = artifacts.data?.get(p.artifact_id)
    return {
      name: a?.title ?? `artifact ${shortId(p.artifact_id)}`,
      size: a?.size_bytes != null ? formatBytes(a.size_bytes) : undefined,
      href: href(`/artifacts/${p.artifact_id}`),
    }
  }

  function sessionTile(p: PhaseExecutionDetail) {
    if (!p.session_id) return null
    return { id: shortId(p.session_id), note: 'platform session · no local transcript', href: href(`/sessions/${p.session_id}`) }
  }

  // Cancel: two presses, so a stray tap never stops a run.
  let confirming = $state(false)
  let cancelling = $state(false)
  let cancelError = $state<string | null>(null)
  async function cancel() {
    if (!confirming) {
      confirming = true
      return
    }
    cancelling = true
    cancelError = null
    try {
      await cancelExecution(id)
      exec.refresh()
    } catch (e) {
      cancelError = e instanceof Error ? e.message : String(e)
    } finally {
      cancelling = false
      confirming = false
    }
  }

  function errorText(e: unknown): string {
    if (e instanceof ApiError) return typeof e.detail === 'string' ? e.detail : `The server answered ${e.status}.`
    return e instanceof Error ? e.message : String(e)
  }
  const notFound = $derived(exec.error instanceof ApiError && exec.error.status === 404)
  const repoName = (url: string) => url.replace(/^https?:\/\/github\.com\//, '').replace(/\.git$/, '')
</script>

{#if exec.error && !d}
  {#if notFound}
    <EmptyState title="Execution not found" description={`No execution has the ID ${id}. It may belong to another instance.`}>
      {#snippet action()}<Button onclick={() => history.back()}>Go back</Button>{/snippet}
    </EmptyState>
  {:else}
    <Callout tone="danger" title="This execution did not load." role="alert">
      {errorText(exec.error)}
      {#snippet action()}<Button size="sm" onclick={() => exec.refresh()}>Retry</Button>{/snippet}
    </Callout>
  {/if}
{:else if !d}
  <div class="sky-exec" aria-busy="true">
    <Skeleton label="Loading execution" variant="block" height="14rem" />
    <Skeleton variant="block" height="10rem" />
    <Skeleton variant="block" height="18rem" />
  </div>
{:else}
  <div class="sky-exec">
    <PageHeader
      class="sky-exec__header"
      kind="execution"
      eyebrow={d.workflow_execution_id}
      status={d.status}
      meta={`${phaseProgressText(d.phase_progress?.display, d.completed_phases, d.total_phases)} · ${formatDateTime(d.started_at)}`}
      titleLabel={d.task ? 'Task' : undefined}
      title={d.task || d.workflow_name}
      {figures}
    >
      {#snippet titleAction()}
        {#if d.task}<CopyButton text={d.task} label="Copy task" copiedLabel="Copied the task" />{/if}
      {/snippet}
      {#snippet actions()}
        <CopyButton variant="label" text={() => runIdentityText(d)} label="Copy run identity" copiedLabel="Copied the run identity" />
        {#if canCancel(d.status)}
          <Button tone="danger" disabled={cancelling} onclick={cancel}>{confirming ? 'Confirm cancel' : 'Cancel run'}</Button>
        {/if}
        <a class="sky-exec__primary" href={href(`/workflows/${d.workflow_id}`)}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.25 8a5.25 5.25 0 1 1-1.6-3.77M13.25 2.5v2.75H10.5"></path></svg>
          Run again
        </a>
      {/snippet}
      <div class="sky-exec__context">
        <a href={href(`/workflows/${d.workflow_id}`)}>{d.workflow_name}</a>
        {#each d.repos ?? [] as repo (repo)}
          <span aria-hidden="true">·</span>
          <a href={repo} target="_blank" rel="noopener noreferrer">{repoName(repo)}</a>
        {/each}
        {#if ev}
          <span aria-hidden="true">·</span>
          <a class="sky-exec__eval" href={href(ev.href)} title={ev.title}>{ev.label}: {d.eval?.eval_name || d.eval?.eval_id}</a>
        {/if}
        {#if live}
          <span class="sky-exec__live" role="status"><span class="sky-exec__pulse" aria-hidden="true"></span>Live</span>
        {/if}
      </div>
    </PageHeader>

    {#if cancelError}
      <Callout tone="danger" title="Cancel failed." role="alert">{cancelError}</Callout>
    {/if}
    {#if exec.error}
      <Callout tone="warning" title="Not updating.">Showing the last values that loaded. {errorText(exec.error)}</Callout>
    {/if}
    {#if failed && d.error_message}
      <Callout tone={failed} title={failed === 'danger' ? 'Execution failed.' : 'A phase reported failure.'}>
        {d.error_message}
        {#if d.reported_failure_reason}
          <span class="sky-exec__quote">The phase attributed it to: {d.reported_failure_reason}</span>
        {/if}
      </Callout>
    {/if}

    <div class="sky-exec__body">
      <div class="sky-exec__side">
        {#if tokens}
          <UsageMeter
            cost={formatCostPrecise(d.total_cost_usd)}
            {tokens}
            costBy="phase"
            costRows={costRowsByPhase(phases)}
            note={usageNote(phases)}
            rates={{
              ...(d.cache_read_rate_display ? { cacheRead: d.cache_read_rate_display } : {}),
              ...(d.cache_write_rate_display ? { cacheWrite: d.cache_write_rate_display } : {}),
            }}
          />
        {/if}
      </div>

      <section class="sky-exec__timeline" aria-labelledby="sky-exec-timeline">
        <div class="sky-exec__timeline-head">
          <h2 id="sky-exec-timeline">Phase timeline</h2>
          <span>Length is time, height is tokens.{caption ? ` ${caption}` : ''} Each phase carries the session it ran in and the artifact it produced.</span>
        </div>
        {#if blocks.length}
          <div class="sky-exec__blocks"><PhaseBlocks phases={blocks} /></div>
        {/if}

        <ol class="sky-exec__phases">
          {#each phases as p, i (p.phase_id + i)}
            {@const kit = phaseKit(p)}
            {@const total = phaseTokens(p)}
            <li class="sky-exec__phase">
              <div class="sky-exec__phase-head">
                <span class="sky-exec__num">{phaseNumber(i)}</span>
                <span class="sky-exec__phase-name">{p.name}</span>
                {#if statusSemantics(p.status).kind !== 'completed'}<StatusBadge status={p.status} />{/if}
                <PhaseKitChips model={phaseModelChip(p)} tools={kit.tools === 'not-recorded' ? 'default' : kit.tools} skills={kit.skills} />
                <span class="sky-exec__grow"></span>
                <span class="sky-exec__dur">{phaseMeta(p).metaShort}</span>
                <span class="sky-exec__cost">{formatCostPrecise(p.cost_usd)}{p.unpriced_observation_count ? '+' : ''}</span>
              </div>
              <div class="sky-exec__phase-tokens">
                <span class="sky-exec__tokbar" aria-hidden="true">
                  {#if total > 0}
                    <span data-series="1" style:flex-grow={p.cache_read_tokens}></span>
                    <span data-series="2" style:flex-grow={p.cache_creation_tokens}></span>
                    <span data-series="3" style:flex-grow={p.output_tokens}></span>
                    <span data-series="4" style:flex-grow={p.input_tokens}></span>
                  {:else}
                    <span data-series="empty" style:flex-grow={1}></span>
                  {/if}
                </span>
                <span class="sky-exec__split">{total > 0 ? phaseTokenSplit(p) : 'no tokens yet'}</span>
              </div>
              {#if p.error_message}
                <p class="sky-exec__phase-error">{p.error_message}</p>
              {/if}
              <RunTiles class="sky-exec__tiles" phase={p.name} session={sessionTile(p)} artifact={artifactTile(p)} />
            </li>
          {/each}
          {#each notStarted as p, j (p.phase_id)}
            <li class="sky-exec__phase" data-pending>
              <div class="sky-exec__phase-head">
                <span class="sky-exec__num">{phaseNumber(phases.length + j)}</span>
                <span class="sky-exec__phase-name">{p.name}</span>
                <StatusBadge status={p.status} label={p.status_display} />
              </div>
            </li>
          {/each}
        </ol>
        {#if !phases.length && !notStarted.length}
          <EmptyState bare level={3} title="No phases recorded" description="This run has not started a phase yet. It appears here as soon as one starts." />
        {/if}

        <ProvenanceStrip {...provenance} busy={inventory.loading} onaction={() => inventory.refresh()} />
      </section>
    </div>
  </div>
{/if}

<style>
  .sky-exec {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    min-width: 0;
  }
  .sky-exec__context {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1-5) var(--ds-space-2);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-exec__context a {
    color: var(--ds-color-text-muted);
  }
  .sky-exec__context a.sky-exec__eval {
    padding: 0 var(--ds-space-2);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-accent-ring);
    background: var(--sky-color-accent-soft);
    color: var(--sky-color-accent-soft-fg);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    text-decoration: none;
  }
  .sky-exec__context a:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-exec__context a:hover {
    color: var(--ds-color-fg);
  }
  .sky-exec__context a:focus-visible,
  .sky-exec__primary:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-exec__live {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    color: var(--sky-color-accent-soft-fg);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
  }
  .sky-exec__pulse {
    width: 8px;
    height: 8px;
    border-radius: var(--ds-radius-full);
    background: var(--ds-color-accent);
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-exec__pulse {
      animation: sky-exec-pulse 1.6s ease-in-out infinite;
    }
  }
  @keyframes sky-exec-pulse {
    50% {
      opacity: 0.35;
    }
  }
  .sky-exec__primary {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--ds-space-2);
    height: var(--sky-size-control-md);
    padding: 0 var(--ds-space-4);
    border-radius: var(--ds-radius-lg);
    background: var(--sky-color-accent-solid);
    box-shadow: var(--sky-shadow-glow);
    color: var(--sky-color-accent-solid-contrast);
    font-size: var(--ds-text-sm);
    font-weight: 600;
    text-decoration: none;
  }
  .sky-exec__quote {
    display: block;
    margin-top: var(--ds-space-2);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-exec__body {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    min-width: 0;
  }
  .sky-exec__side,
  .sky-exec__timeline {
    min-width: 0;
  }
  .sky-exec__timeline {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    padding: var(--ds-space-4) var(--ds-space-4) var(--ds-space-3);
    border-radius: var(--sky-radius-card-lg);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background:
      radial-gradient(70% 70% at 60% 100%, var(--sky-color-accent-soft), transparent 75%),
      var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-exec__timeline-head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--ds-space-1) var(--ds-space-3);
    color: var(--ds-color-text-muted);
    font-size: var(--ds-text-sm);
  }
  .sky-exec__timeline-head h2 {
    margin: 0;
    font-size: var(--ds-text-xl);
    font-weight: 600;
    letter-spacing: -0.015em;
    color: var(--ds-color-fg);
  }
  .sky-exec__blocks {
    overflow-x: auto;
  }
  .sky-exec__phases {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin: var(--ds-space-1-5) 0 0;
    padding: var(--ds-space-2-5) 0 0;
    border-top: var(--ds-border-width) solid var(--ds-color-border);
    list-style: none;
  }
  .sky-exec__phase {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
    padding: var(--ds-space-3-5) var(--ds-space-1);
    border-radius: var(--sky-radius-control);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-exec__phase[data-pending] {
    opacity: 0.7;
  }
  .sky-exec__phase-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2) var(--ds-space-3);
  }
  .sky-exec__num {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 28px;
    height: 28px;
    border-radius: 9px;
    background: var(--sky-color-accent-soft);
    color: var(--ds-color-accent);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    font-weight: 600;
  }
  .sky-exec__phase-name {
    font-size: var(--ds-text-md);
    font-weight: 600;
    color: var(--ds-color-fg);
  }
  .sky-exec__grow {
    flex-grow: 1;
  }
  .sky-exec__dur,
  .sky-exec__cost,
  .sky-exec__split {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
  }
  .sky-exec__cost {
    min-width: 60px;
    text-align: right;
    color: var(--ds-color-fg);
  }
  .sky-exec__phase-tokens,
  .sky-exec__phase > :global(.sky-exec__tiles),
  .sky-exec__phase-error {
    padding-left: 0;
  }
  .sky-exec__phase-tokens {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1-5) var(--ds-space-3);
  }
  .sky-exec__tokbar {
    display: flex;
    gap: 2px;
    width: 84px;
    height: 6px;
  }
  .sky-exec__tokbar > span {
    flex-basis: 0;
    border-radius: 2px;
  }
  [data-series='1'] {
    background: var(--sky-color-data-1);
  }
  [data-series='2'] {
    background: var(--sky-color-data-2);
  }
  [data-series='3'] {
    background: var(--sky-color-data-3);
  }
  [data-series='4'] {
    background: var(--sky-color-data-4);
  }
  [data-series='empty'] {
    background: var(--sky-color-track);
  }
  .sky-exec__phase-error {
    margin: 0;
    color: var(--sky-color-danger-soft-fg);
  }

  @media (min-width: 48rem) {
    .sky-exec {
      gap: var(--ds-space-7);
    }
    .sky-exec__timeline {
      padding: var(--ds-space-6) var(--ds-space-6) var(--ds-space-3-5);
    }
    .sky-exec__phase {
      padding: var(--ds-space-3-5) var(--ds-space-2-5);
    }
    .sky-exec__phase:hover {
      background: var(--ds-color-surface-raised);
    }
    .sky-exec__phase-tokens,
    .sky-exec__phase > :global(.sky-exec__tiles),
    .sky-exec__phase-error {
      padding-left: 40px;
    }
  }
  @media (min-width: 64rem) {
    .sky-exec__body {
      display: grid;
      grid-template-columns: minmax(0, 1fr) var(--sky-side-column);
      align-items: start;
      gap: var(--ds-space-7) var(--ds-space-8);
    }
    .sky-exec__side {
      grid-column: 2;
      grid-row: 1;
      position: sticky;
      top: var(--ds-space-4);
    }
    .sky-exec__timeline {
      grid-column: 1;
      grid-row: 1;
    }
  }
</style>
