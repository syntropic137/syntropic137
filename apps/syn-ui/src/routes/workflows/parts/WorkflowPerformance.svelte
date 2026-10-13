<!--
  Workflow Performance panel (Workflow, PhoneWorkflow boards): four summary
  cards, one Success / Speed / Cost / Tokens chart with a dot per run in its
  outcome colour, a run readout and a duration graph per phase. All maths is
  skyline-core workflowPerformance; this part renders it and keeps the
  selected run and metric. A server without GET /workflows/{id}/trend (404)
  gets a note, never a broken panel.
-->
<script lang="ts">
  import { ApiError, type DefinitionChange, type WorkflowTrendRow } from '@syn137/syn-ui-data'
  import { Callout, EmptyState, Skeleton, ToggleGroup } from '@syn137/skyline-svelte-v5'
  import { TrendChart } from '@syn137/skyline-svelte-v5/patterns'
  import { PERF_METRICS, PERF_VIEW_HEIGHT, parsePerfMetric, perfReadout, stepPerfRun, workflowPerformance, type PerfMetric, type PerfTone } from '@syn137/skyline-core/screens/workflows'
  import { href } from '../../../lib/router'

  interface Props {
    rows: WorkflowTrendRow[] | null
    changes: DefinitionChange[]
    error: unknown
  }

  let { rows, changes, error }: Props = $props()

  let metric = $state<PerfMetric>('cost')
  let picked = $state(-1)

  const model = $derived(workflowPerformance(rows ?? [], metric, changes))
  const sel = $derived(picked >= 0 && picked < model.runs.length ? picked : model.initial)
  const readout = $derived(perfReadout(model, sel))
  const pick = (i: number) => (picked = i)
  const unavailable = $derived(error instanceof ApiError && error.status === 404)

  const ARROW: Record<PerfTone, string> = {
    good: 'M3 10.5l3.5-3.5 2.5 2.5L13 5.5M9.5 5.5H13V9',
    bad: 'M3 5.5L6.5 9 9 6.5l4 4M9.5 10.5H13V7',
    neutral: 'M3 8h10',
  }
  const errText = (x: unknown) => (x instanceof Error ? x.message : String(x))
</script>

<section class="sky-wperf" aria-labelledby="sky-wperf-title">
  <div class="sky-wperf__head">
    <div class="sky-wperf__titles">
      <h2 id="sky-wperf-title">Performance</h2>
      <span>{rows && !model.empty ? model.subtitle : 'Success, speed, cost and tokens across this workflow’s runs.'}</span>
    </div>
    {#if rows && !model.empty}
      <ToggleGroup
        type="single"
        variant="segmented"
        aria-label="Metric"
        items={PERF_METRICS.map((m) => ({ value: m.value, label: m.label }))}
        value={[metric]}
        onValueChange={(v) => (metric = parsePerfMetric(v[0]))}
      />
    {/if}
  </div>

  {#if unavailable}
    <p class="sky-wperf__note" role="note">Run history is not available on this server yet. It needs <code>GET /workflows/&#123;id&#125;/trend</code>; the rest of this page works without it.</p>
  {:else if error && !rows}
    <Callout tone="warning" title="Could not load the run history">{errText(error)}</Callout>
  {:else if !rows}
    <Skeleton variant="block" height="22rem" />
  {:else if model.empty}
    <EmptyState bare level={3} title="No runs yet" description="Each finished run adds a dot here, with its time, cost and tokens." />
  {:else}
    <ul class="sky-wperf__kpis" aria-label="Summary">
      {#each model.kpis as k (k.label)}
        <li class="sky-wperf__kpi">
          <span class="sky-wperf__kpi-label">{k.label}</span>
          <span class="sky-wperf__kpi-value">{k.value}</span>
          <span class="sky-wperf__word" data-tone={k.tone}><svg width="11" height="11" viewBox="0 0 16 16" aria-hidden="true"><path d={ARROW[k.tone]} /></svg>{k.word}</span>
          <span class="sky-wperf__delta">{k.delta}</span>
        </li>
      {/each}
    </ul>

    <div class="sky-wperf__main">
      <div class="sky-wperf__chart">
        <span class="sky-wperf__caption">
          <span><strong>{model.title}</strong> · {model.unit}</span>
          <span class="sky-wperf__legend">
            <span><span class="sky-wperf__key" data-tone="completed" aria-hidden="true"></span>Completed</span>
            <span><span class="sky-wperf__key" data-tone="failed" aria-hidden="true"></span>Failed</span>
            <span><span class="sky-wperf__key" data-tone="cancelled" aria-hidden="true"></span>Cancelled</span>
          </span>
        </span>
        <TrendChart
          aria-label={`${model.title} by run`}
          role="group"
          lines={model.lines}
          dots={model.dots}
          ends={model.ends}
          yTicks={model.yTicks}
          xTicks={model.xTicks}
          notes={model.notes}
          noteLabels
          viewHeight={PERF_VIEW_HEIGHT}
          selected={sel}
          hair={readout?.x ?? null}
          onpick={pick}
        />
      </div>

      {#if readout}
        <div class="sky-wperf__readout" role="status" aria-live="polite">
          <div class="sky-wperf__readout-top">
            <span class="sky-wperf__eyebrow">Run</span>
            <span class="sky-wperf__steps">
              <button type="button" aria-label="Previous run" onclick={() => pick(stepPerfRun(model, sel, -1))}><svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3.5L5.5 8 10 12.5" /></svg></button>
              <button type="button" aria-label="Next run" onclick={() => pick(stepPerfRun(model, sel, 1))}><svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5" /></svg></button>
            </span>
          </div>
          <div class="sky-wperf__who">
            <span class="sky-wperf__date">{readout.date}</span>
            <span class="sky-wperf__id">{readout.id}</span>
          </div>
          <span class="sky-wperf__pill" data-tone={readout.status}>{readout.statusWord}</span>
          <dl class="sky-wperf__figs">
            <div><dt>Duration</dt><dd>{readout.speed}</dd></div>
            <div><dt>Cost</dt><dd>{readout.cost}</dd></div>
            <div><dt>Success</dt><dd>{readout.success}</dd></div>
          </dl>
          <a class="sky-wperf__open" href={href(`/executions/${encodeURIComponent(readout.executionId)}`)}>Open this run <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5" /></svg></a>
        </div>
      {/if}
    </div>

    {#if model.phases.length}
      <div class="sky-wperf__phases">
        <span class="sky-wperf__eyebrow">Phase duration, completed runs</span>
        <ul>
          {#each model.phases as ph (ph.key)}
            <li class="sky-wperf__phase" aria-label={ph.label}>
              <span class="sky-wperf__phase-text">
                <span class="sky-wperf__phase-name">{ph.name}</span>
                <span class="sky-wperf__phase-now">{ph.now} <span data-tone={ph.tone}>{ph.delta}</span></span>
              </span>
              <svg class="sky-wperf__spark" viewBox="0 0 200 48" preserveAspectRatio="none" aria-hidden="true"><path d={ph.spark} vector-effect="non-scaling-stroke" /></svg>
            </li>
          {/each}
        </ul>
      </div>
    {/if}
  {/if}
</section>

<style>
  .sky-wperf {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-card-lg);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  svg path {
    fill: none;
    stroke: currentColor;
    stroke-width: 1.75;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  code {
    font-family: var(--ds-font-mono);
  }
  .sky-wperf__head {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--ds-space-3) var(--ds-space-6);
  }
  .sky-wperf__titles {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    flex: 1 1 20rem;
    min-width: 0;
  }
  .sky-wperf__titles h2 {
    margin: 0;
    font-size: var(--ds-text-lg);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
  }
  .sky-wperf__titles > span,
  .sky-wperf__note {
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-wperf__note {
    margin: 0;
    padding: var(--ds-space-3) var(--ds-space-3-5);
    border-radius: var(--sky-radius-control);
    border: var(--ds-border-width) dashed var(--sky-color-border-hover);
  }
  .sky-wperf__kpis {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--ds-space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-wperf__kpi {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
    min-width: 0;
    padding: var(--ds-space-3) var(--ds-space-3-5);
    border-radius: var(--sky-radius-row);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-bg);
  }
  .sky-wperf__kpi-label {
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-wperf__kpi-value {
    font-size: var(--ds-text-2xl);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums;
  }
  .sky-wperf__word {
    align-self: flex-start;
    display: flex;
    align-items: center;
    gap: var(--ds-space-1);
    height: 1.25rem;
    padding: 0 7px;
    border-radius: var(--ds-radius-full);
    background: var(--sky-color-neutral-soft);
    color: var(--ds-color-text-muted);
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-wperf__word[data-tone='good'] {
    background: var(--sky-color-success-soft);
    color: var(--sky-color-success-soft-fg);
  }
  .sky-wperf__word[data-tone='bad'] {
    background: var(--sky-color-danger-soft);
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-wperf__delta {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-wperf__main {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    min-width: 0;
  }
  .sky-wperf__chart {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
    flex: 1 1 auto;
    min-width: 0;
  }
  .sky-wperf__caption {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-1-5) var(--ds-space-4);
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
  .sky-wperf__caption strong {
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
  }
  .sky-wperf__legend {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-1-5) var(--ds-space-3);
    font-size: var(--ds-text-xs);
  }
  .sky-wperf__legend > span {
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .sky-wperf__key {
    width: 9px;
    height: 9px;
    border-radius: 50%;
  }
  [data-tone='completed'].sky-wperf__key {
    background: var(--sky-status-completed);
  }
  [data-tone='failed'].sky-wperf__key {
    background: var(--sky-status-failed);
  }
  [data-tone='cancelled'].sky-wperf__key {
    background: var(--sky-status-cancelled);
  }
  .sky-wperf__readout {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    padding: var(--ds-space-4);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-bg);
  }
  .sky-wperf__readout-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-2);
  }
  .sky-wperf__eyebrow {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-wperf__steps {
    display: flex;
    gap: var(--ds-space-1);
  }
  .sky-wperf__steps button {
    display: flex;
    align-items: center;
    justify-content: center;
    width: var(--sky-size-touch);
    height: var(--sky-size-touch);
    padding: 0;
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    border-radius: 9px;
    background: var(--sky-color-control);
    color: var(--sky-color-text-code);
    cursor: pointer;
  }
  .sky-wperf__steps button:hover {
    background: var(--sky-color-control-hover);
  }
  .sky-wperf__steps button:focus-visible,
  .sky-wperf__open:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-wperf__who {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
  }
  .sky-wperf__date {
    font-size: var(--ds-text-md);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-wperf__id {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
    overflow-wrap: anywhere;
  }
  .sky-wperf__pill {
    align-self: flex-start;
    height: 1.5rem;
    padding: 0 11px;
    border-radius: var(--ds-radius-full);
    background: var(--sky-color-neutral-soft);
    color: var(--ds-color-text-muted);
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-semibold);
    line-height: 1.5rem;
  }
  .sky-wperf__pill[data-tone='completed'] {
    background: var(--sky-color-success-soft);
    color: var(--sky-color-success-soft-fg);
  }
  .sky-wperf__pill[data-tone='failed'] {
    background: var(--sky-color-danger-soft);
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-wperf__figs {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--ds-space-2);
    margin: 0;
  }
  .sky-wperf__figs div {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
  }
  .sky-wperf__figs dt {
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-wperf__figs dd {
    margin: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-sm);
  }
  .sky-wperf__open {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
    text-decoration: none;
  }
  .sky-wperf__phases {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
    padding-top: var(--ds-space-3-5);
    border-top: var(--ds-border-width) solid var(--ds-color-border);
  }
  .sky-wperf__phases ul {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--ds-space-2-5);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-wperf__phase {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 6rem;
    align-items: center;
    gap: var(--ds-space-3);
    padding: var(--ds-space-3) var(--ds-space-3-5);
    border-radius: var(--sky-radius-row);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-bg);
  }
  .sky-wperf__phase-text {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  .sky-wperf__phase-name {
    overflow: hidden;
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .sky-wperf__phase-now {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
  }
  .sky-wperf__phase-now span {
    color: var(--ds-color-text-muted);
  }
  .sky-wperf__phase-now span[data-tone='good'] {
    color: var(--sky-color-success-soft-fg);
  }
  .sky-wperf__phase-now span[data-tone='bad'] {
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-wperf__spark {
    width: 6rem;
    height: 2rem;
    overflow: visible;
    color: var(--ds-color-accent);
  }
  .sky-wperf__spark path {
    stroke-width: 2;
  }
  @media (min-width: 48rem) {
    .sky-wperf {
      padding: var(--ds-space-6);
    }
    .sky-wperf__titles h2 {
      font-size: var(--ds-text-xl);
    }
    .sky-wperf__titles > span {
      font-size: var(--ds-text-md);
    }
    .sky-wperf__kpis {
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: var(--ds-space-2-5);
    }
    .sky-wperf__kpi {
      padding: var(--ds-space-3-5) var(--ds-space-4);
    }
    .sky-wperf__phases ul {
      grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
    }
  }
  @media (min-width: 64rem) {
    .sky-wperf__main {
      flex-direction: row;
      align-items: stretch;
    }
    .sky-wperf__readout {
      flex: 0 0 15.5rem;
      align-self: flex-start;
    }
    .sky-wperf__steps button {
      width: 1.875rem;
      height: 1.875rem;
    }
  }
  @media (min-width: 64rem) and (pointer: coarse) {
    .sky-wperf__steps button {
      width: var(--sky-size-touch);
      height: var(--sky-size-touch);
    }
  }
</style>
