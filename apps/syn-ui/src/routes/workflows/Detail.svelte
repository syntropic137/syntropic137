<!--
  Workflow (boards: Workflow, PhoneWorkflow, PhaseKit). One responsive page:
  base styles are the phone board, the phase grid widens from 48rem.
  - Header: Page Header with the type and repo tags, declared skills,
    "Copy for an agent" (Agent Prompt Button) and Run workflow.
  - Performance: GET /workflows/{id}/trend through skyline-core
    workflowPerformance (parts/WorkflowPerformance).
  - Pipeline: one card per phase with its kit; the selected phase shows its
    kit, timeout, latest output (GET /workflows/{id}/latest-outputs) and
    prompt. Token shares come from GET /workflows/{id}/history when it has
    runs (API gap: the history endpoint is deprecated and often empty).
  - Recent runs: the newest five, linking to the Runs page.
  Endpoints a server does not have yet (404) degrade to a note.
-->
<script lang="ts">
  import { formatCost, formatInteger, formatPercent, formatRelativeTime, formatTokens, formatDuration } from '@syn137/skyline-core/format'
  import { runBarPercent, runSegments, runSlots } from '@syn137/skyline-core/patterns'
  import {
    formatTimeout,
    latestOutputsByPhase,
    parsePrompt,
    phaseKitOf,
    phaseModelChip,
    phaseShares,
    runDurationMs,
    workflowFigures,
    workflowPromptSpec,
    workflowSkillRefs,
    workflowTags,
  } from '@syn137/skyline-core/screens/workflows'
  import { Button, Callout, EmptyState, Skeleton } from '@syn137/skyline-svelte-v5'
  import { AgentPromptButton, HarnessChip, PageHeader, PhaseKit, PhaseKitChips, RunRow, SkillRef } from '@syn137/skyline-svelte-v5/patterns'
  import { ApiError, TREND_PAGE_SIZE, getWorkflow, getWorkflowHistory, getWorkflowLatestOutputs, getWorkflowTrend, listWorkflowRuns } from '@syn137/syn-ui-data'
  import { isRunEvent } from '@syn137/syn-ui-data/live'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import { href } from '../../lib/router'
  import type { PageProps } from '../../lib/routes'
  import RunWorkflow from './parts/RunWorkflow.svelte'
  import WorkflowPerformance from './parts/WorkflowPerformance.svelte'

  let { params }: PageProps = $props()
  const id = $derived(params.workflowId ?? '')

  const wf = resource((signal) => getWorkflow(id, signal))
  const runs = resource((signal) => listWorkflowRuns(id, signal), { live: isRunEvent })
  const trend = resource((signal) => getWorkflowTrend(id, { page_size: TREND_PAGE_SIZE }, signal), { live: isRunEvent })
  const outputs = resource((signal) => getWorkflowLatestOutputs(id, signal))
  const history = resource((signal) => getWorkflowHistory(id, signal))

  $effect(() => {
    if (wf.data) setPage({ title: wf.data.name, crumbs: [{ label: 'Workflows', href: '/workflows' }, { label: wf.data.name }] })
  })

  let running = $state(false)
  let selected = $state<string | null>(null)

  const w = $derived(wf.data)
  const phases = $derived(w ? [...w.phases].sort((a, b) => a.order - b.order) : [])
  const current = $derived(phases.find((p) => p.phase_id === selected) ?? phases[0])
  const figures = $derived(w ? workflowFigures(phases.length, w.runs_count, runs.data ?? null) : [])
  const skills = $derived(workflowSkillRefs(phases))
  const prompt = $derived(w ? workflowPromptSpec({ id: w.id, name: w.name, phases, input_declarations: w.input_declarations }) : null)
  const shares = $derived(history.data?.executions.length ? phaseShares(phases.map((p) => p.phase_id), history.data.executions) : null)
  const latest = $derived(outputs.data ? latestOutputsByPhase(outputs.data.phases) : null)
  const outputsMissing = $derived(outputs.error instanceof ApiError && outputs.error.status === 404)
  const notFound = $derived(wf.error instanceof ApiError && wf.error.status === 404)

  const now = $derived(runs.data ? Date.now() : 0)
  const recent = $derived((runs.data ?? []).slice(0, 5))
  const longest = $derived(Math.max(0, ...recent.map((r) => runDurationMs(r, now || Date.now()) ?? 0)))
  const slots = $derived(runSlots(recent.map((r) => r.phase_progress?.possible ?? r.total_phases)))
  const runsHref = $derived(href(`/workflows/${id}/runs`))
  const totalRuns = $derived(Math.max(w?.runs_count ?? 0, runs.data?.length ?? 0))

  function errorText(e: unknown): string {
    if (e instanceof ApiError) return typeof e.detail === 'string' ? e.detail : `The server answered ${e.status}.`
    return e instanceof Error ? e.message : String(e)
  }
</script>

{#if notFound}
  <EmptyState title="Workflow not found" description={`No workflow has the ID ${id}.`}>
    {#snippet action()}<Button href={href('/workflows')}>Back to workflows</Button>{/snippet}
  </EmptyState>
{:else if wf.error && !w}
  <Callout tone="danger" title="The workflow did not load." role="alert">
    {errorText(wf.error)}
    {#snippet action()}<Button size="sm" onclick={() => wf.refresh()}>Retry</Button>{/snippet}
  </Callout>
{:else if !w}
  <div class="sky-wf" aria-busy="true">
    <Skeleton label="Loading the workflow" variant="block" height="14rem" />
    <Skeleton variant="block" height="20rem" />
  </div>
{:else}
  <div class="sky-wf">
    <PageHeader kind="workflow" eyebrow={w.id} title={w.name} description={w.description?.trim() || `${w.workflow_type} workflow`} {figures}>
      {#snippet actions()}
        <Button variant="solid" aria-expanded={running} aria-controls="sky-wf-run" onclick={() => (running = !running)}>
          {#snippet icon()}<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M4.5 2.75v10.5L13 8z"></path></svg>{/snippet}
          Run workflow
        </Button>
        <Button href={runsHref}>All {totalRuns} runs</Button>
      {/snippet}
      <ul class="sky-wf__tags" aria-label="About this workflow">
        {#each workflowTags(w) as t (t)}<li>{t}</li>{/each}
      </ul>
      {#if skills.length}
        <ul class="sky-wf__skills" aria-label="Declared skills">
          {#each skills as s (s.name)}
            <li><SkillRef variant="chip" {...s} /></li>
          {/each}
        </ul>
      {/if}
      {#if prompt}<div class="sky-wf__prompt-copy"><AgentPromptButton {prompt} label="Copy for an agent" /></div>{/if}
    </PageHeader>

    {#if running}
      <div id="sky-wf-run">
        <RunWorkflow workflowId={w.id} declarations={w.input_declarations ?? []} {phases} onclose={() => (running = false)} />
      </div>
    {/if}

    <WorkflowPerformance rows={trend.data?.items ?? null} changes={trend.data?.definition_changes ?? []} error={trend.error} />

    <section class="sky-wf__section" aria-labelledby="sky-wf-pipeline">
      <div class="sky-wf__section-head">
        <h2 id="sky-wf-pipeline">Pipeline</h2>
        <span>{phases.length} {phases.length === 1 ? 'phase' : 'phases'}, run top to bottom. Pick one for its prompt and what it gets.</span>
      </div>
      {#if phases.length === 0}
        <EmptyState bare level={3} title="No phases" description="This workflow declares no phases." />
      {:else}
        <ol class="sky-wf__phases">
          {#each phases as p, i (p.phase_id)}
            {@const kit = phaseKitOf(p)}
            {@const share = shares?.[p.phase_id]}
            {@const agent = kit.model && kit.model !== 'not-recorded' ? kit.model : null}
            <li>
              <button type="button" class="sky-wf__phase" aria-pressed={current?.phase_id === p.phase_id} aria-controls="sky-wf-phase-detail" onclick={() => (selected = p.phase_id)}>
                <span class="sky-wf__phase-top">
                  <span class="sky-wf__phase-num">{String(i + 1).padStart(2, '0')}</span>
                  <HarnessChip provider={agent?.agentKind && agent.agentKind !== 'other' ? agent.agentKind : (agent?.agent ?? '')} label={agent?.agent ?? 'Agent'} />
                </span>
                <span class="sky-wf__phase-name">{p.name}</span>
                {#if p.description}<span class="sky-wf__phase-desc">{p.description}</span>{/if}
                <PhaseKitChips class="sky-wf__chips" model={phaseModelChip(p)} tools={kit.tools === 'not-recorded' ? 'default' : kit.tools} skills={kit.skills} />
                {#if share}
                  <span class="sky-wf__share" aria-hidden="true"><span style:width={`${Math.round(share.share * 100)}%`}></span></span>
                  <span class="sky-wf__share-text"><span>{formatInteger(share.tokens)} tok · {formatPercent(share.share)}</span><span>{formatCost(share.cost)}</span></span>
                {/if}
              </button>
            </li>
          {/each}
        </ol>

        {#if current}
          {@const kit = phaseKitOf(current)}
          {@const out = latest?.[current.phase_id]}
          <div class="sky-wf__detail" id="sky-wf-phase-detail" role="region" aria-label={`Prompt · ${current.name}`}>
            <div class="sky-wf__detail-head">
              <span>Prompt · {current.name}</span>
            </div>
            <div class="sky-wf__kit">
              <PhaseKit card={false} model={kit.model} tools={kit.tools} toolsNote={kit.toolsNote} skills={kit.skills} />
              <dl class="sky-wf__facts">
                <div><dt>Timeout</dt><dd class="sky-wf__mono">{formatTimeout(current.timeout_seconds)}</dd></div>
                <div>
                  <dt>Latest output</dt>
                  <dd>
                    {#if outputsMissing}
                      <span class="sky-wf__muted">Not available on this server yet</span>
                    {:else if outputs.error && !outputs.data}
                      <span class="sky-wf__muted">Could not load: {errorText(outputs.error)}</span>
                    {:else if !latest}
                      <Skeleton variant="text" width="10rem" />
                    {:else if out}
                      <a class="sky-wf__mono" href={href(`/artifacts/${encodeURIComponent(out.artifactId)}`)}>{out.title}</a>
                      <span class="sky-wf__muted sky-wf__mono">{out.meta}</span>
                    {:else}
                      <span class="sky-wf__muted">Nothing yet</span>
                    {/if}
                  </dd>
                </div>
              </dl>
            </div>
            <div class="sky-wf__prompt">
              {#each parsePrompt(current.prompt_template) as b, k (k)}
                {#if b.kind === 'heading'}
                  <h3>{b.text}</h3>
                {:else if b.kind === 'paragraph'}
                  <p>{b.text}</p>
                {:else if b.kind === 'list'}
                  <ul>{#each b.items as item, j (j)}<li>{item}</li>{/each}</ul>
                {:else}
                  <p><code class="sky-wf__arg">{b.name}</code> <span class="sky-wf__muted">filled from the task you enter at kickoff</span></p>
                {/if}
              {:else}
                <p class="sky-wf__muted">This phase has no prompt template.</p>
              {/each}
            </div>
          </div>
        {/if}
      {/if}
    </section>

    <section class="sky-wf__section" aria-labelledby="sky-wf-runs">
      <div class="sky-wf__section-head sky-wf__section-head--row">
        <h2 id="sky-wf-runs">Recent runs</h2>
        <a class="sky-wf__all" href={runsHref}>View all {totalRuns} →</a>
      </div>
      {#if runs.error && !runs.data}
        <Callout tone="warning" title="Runs did not load.">{errorText(runs.error)}</Callout>
      {:else if !runs.data}
        <Skeleton label="Loading runs" variant="block" height="3.5rem" />
      {:else if recent.length === 0}
        <EmptyState bare level={3} title="No runs yet" description="Start one with Run workflow, or copy the prompt for an agent." />
      {:else}
        <ul class="sky-wf__runs">
          {#each recent as r (r.workflow_execution_id)}
            {@const ms = runDurationMs(r, now || Date.now())}
            {@const when = formatRelativeTime(r.started_at, { now: now || Date.now() })}
            <li>
              <RunRow
                href={href(`/executions/${r.workflow_execution_id}`)}
                status={r.status}
                name={r.workflow_execution_id}
                sub={r.phase_progress?.display ?? `${r.completed_phases} of ${r.total_phases} phases`}
                segments={runSegments({ status: r.status, done: r.phase_progress?.completed ?? r.completed_phases, total: r.phase_progress?.possible ?? r.total_phases })}
                barPercent={runBarPercent(ms, longest)}
                {slots}
                duration={formatDuration(ms)}
                tokens={formatTokens(r.total_tokens)}
                cost={formatCost(r.total_cost_usd)}
                {when}
                aria-label={`${r.workflow_execution_id}, ${r.status}, started ${when}`}
              />
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  </div>
{/if}

<style>
  .sky-wf {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-6);
    min-width: 0;
  }
  .sky-wf__tags,
  .sky-wf__skills {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-wf__tags li {
    height: 1.375rem;
    padding: 0 var(--ds-space-2);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    line-height: 1.25rem;
    color: var(--ds-color-text-muted);
  }
  .sky-wf__skills li {
    display: flex;
  }
  .sky-wf__prompt-copy {
    flex: 1 1 100%;
    min-width: 0;
  }
  .sky-wf__section {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
  }
  .sky-wf__section-head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--ds-space-1) var(--ds-space-3);
  }
  .sky-wf__section-head--row {
    justify-content: space-between;
  }
  .sky-wf__section-head h2 {
    margin: 0;
    font-size: var(--ds-text-xl);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
  }
  .sky-wf__section-head > span {
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-wf__all {
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
    text-decoration: none;
  }
  .sky-wf__all:hover {
    color: var(--ds-color-fg);
  }
  .sky-wf__phases {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--ds-space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-wf__phases > li {
    display: flex;
    min-width: 0;
  }
  .sky-wf__phase {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
    width: 100%;
    min-width: 0;
    padding: var(--ds-space-4) var(--ds-space-5);
    border: var(--ds-border-width) solid var(--ds-color-border);
    border-radius: var(--sky-radius-xl);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
    color: var(--ds-color-fg);
    font: inherit;
    text-align: left;
    cursor: pointer;
    transition: border-color var(--sky-duration-fast) ease;
  }
  .sky-wf__phase:hover {
    border-color: var(--sky-color-border-hover);
  }
  .sky-wf__phase[aria-pressed='true'] {
    border-color: var(--sky-color-accent-ring);
    background: var(--ds-color-surface-raised);
  }
  .sky-wf__phase:focus-visible,
  .sky-wf__all:focus-visible,
  .sky-wf__facts a:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-wf__phase-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-2);
  }
  .sky-wf__phase-num {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-wf__phase[aria-pressed='true'] .sky-wf__phase-num {
    color: var(--ds-color-accent);
  }
  .sky-wf__phase-name {
    font-size: var(--ds-text-md);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-wf__phase-desc {
    font-size: var(--ds-text-sm);
    line-height: 1.45;
    color: var(--ds-color-text-muted);
  }
  .sky-wf__phase :global(.sky-wf__chips) {
    margin-top: auto;
  }
  .sky-wf__share {
    display: block;
    height: 4px;
    border-radius: 2px;
    background: var(--sky-color-track);
  }
  .sky-wf__share span {
    display: block;
    height: 100%;
    border-radius: 2px;
    background: var(--ds-color-accent);
  }
  .sky-wf__share-text {
    display: flex;
    justify-content: space-between;
    gap: var(--ds-space-3);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-wf__detail {
    display: flex;
    flex-direction: column;
    min-width: 0;
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-wf__detail-head {
    padding: var(--ds-space-4) var(--ds-space-5);
    border-bottom: var(--ds-border-width) solid var(--ds-color-border);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-wf__kit {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    padding: var(--ds-space-4) var(--ds-space-5);
    border-bottom: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-bg);
  }
  .sky-wf__facts {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--ds-space-4);
    margin: 0;
  }
  .sky-wf__facts div {
    display: flex;
    flex-direction: column;
    gap: 7px;
    min-width: 0;
  }
  .sky-wf__facts dt {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-wf__facts dd {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 4px 8px;
    margin: 0;
    font-size: var(--ds-text-sm);
  }
  .sky-wf__facts a {
    color: var(--ds-color-fg);
    text-decoration: underline;
    text-decoration-color: var(--sky-color-border-hover);
    text-underline-offset: 3px;
  }
  .sky-wf__mono {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
  }
  .sky-wf__muted {
    color: var(--ds-color-text-muted);
  }
  .sky-wf__prompt {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    max-width: 44rem;
    min-width: 0;
    padding: var(--ds-space-5);
    font-size: var(--ds-text-md);
    line-height: 1.6;
    overflow-wrap: anywhere;
  }
  .sky-wf__prompt h3 {
    margin: var(--ds-space-1-5) 0 0;
    font-size: var(--ds-text-md);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-wf__prompt p,
  .sky-wf__prompt ul {
    margin: 0;
  }
  .sky-wf__prompt ul {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding-left: 20px;
  }
  .sky-wf__arg {
    padding: 4px 10px;
    border-radius: 8px;
    background: var(--sky-color-accent-soft);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
  }
  .sky-wf__runs {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  @media (min-width: 48rem) {
    .sky-wf {
      gap: var(--ds-space-8);
    }
    .sky-wf__phases {
      grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
      gap: var(--ds-space-3-5);
    }
    .sky-wf__facts {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .sky-wf__runs {
      gap: 2px;
      padding: var(--ds-space-2-5);
      border-radius: var(--sky-radius-card-lg);
      border: var(--ds-border-width) solid var(--ds-color-border);
      background: var(--ds-color-surface);
      box-shadow: var(--sky-shadow-raised);
    }
  }
</style>
