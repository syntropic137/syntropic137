<!--
  Eval Trend panel (Eval, PhoneEval boards): "Is it getting better, and at
  what cost?". Quality score per verifier over time with the pass line and
  the judge, cost / speed / tokens on the same dates beneath, verifier cards,
  a run readout and verdict lanes. All maths is skyline-core evalTrendModel;
  this part renders it and keeps the selected run and metric.
-->
<script lang="ts">
  import type { DefinitionChange, EvalTrendRow } from '@syn137/syn-ui-data'
  import { Skeleton, ToggleGroup, Callout, EmptyState } from '@syn137/skyline-svelte-v5'
  import { CopyButton, TrendChart } from '@syn137/skyline-svelte-v5/patterns'
  import { buildEvalTrendPrompt, evalTrendCommand } from '@syn137/skyline-core/patterns'
  import { PASS_SCORE, evalTrendModel, stepRun, trendReadout, type TrendDirection, type TrendMetric } from '@syn137/skyline-core/screens/evals'
  import { href } from '../../../lib/router'

  interface Props {
    evalId: string
    evalName: string
    rows: EvalTrendRow[] | null
    changes: DefinitionChange[]
    error: unknown
  }

  let { evalId, evalName, rows, changes, error }: Props = $props()

  let metric = $state<TrendMetric>('cost')
  let picked = $state(-1)

  const model = $derived(evalTrendModel(rows ?? [], metric, changes))
  const sel = $derived(picked >= 0 && picked < model.runs.length ? picked : model.initial)
  const readout = $derived(trendReadout(model, sel))
  const prompt = $derived(buildEvalTrendPrompt({ evalId, evalName }))
  const pick = (i: number) => (picked = i)

  const ARROW: Record<TrendDirection, string> = {
    up: 'M3 10.5l3.5-3.5 2.5 2.5L13 5.5M9.5 5.5H13V9',
    down: 'M3 5.5L6.5 9 9 6.5l4 4M9.5 10.5H13V7',
    flat: 'M3 8h10',
  }
  const JUDGE = 'M8 2.5v11M4.5 13.5h7M3 5h10M3 5l-1.75 4.25a1.9 1.9 0 0 0 3.5 0zM13 5l-1.75 4.25a1.9 1.9 0 0 0 3.5 0z'
  const METRICS = [
    { value: 'cost', label: 'Cost' },
    { value: 'speed', label: 'Speed' },
    { value: 'tokens', label: 'Tokens' },
  ]
  const errText = (x: unknown) => (x instanceof Error ? x.message : String(x))
</script>

<section class="sky-etrend" aria-labelledby="sky-etrend-title">
  <div class="sky-etrend__head">
    <div class="sky-etrend__titles">
      <h2 id="sky-etrend-title">Is it getting better, and at what cost?</h2>
      <span>{rows ? model.subtitle : 'Run history for every verifier of this case.'}</span>
    </div>
    <div class="sky-etrend__agent">
      <CopyButton variant="label" text={prompt} label="Copy for an agent" copiedLabel="Copied agent prompt" />
      <code>{evalTrendCommand(evalId)}</code>
    </div>
  </div>

  {#if error && !rows}
    <Callout tone="warning" title="Could not load the trend">{errText(error)}</Callout>
  {:else if !rows}
    <Skeleton variant="block" height="22rem" />
  {:else if model.empty}
    <EmptyState bare level={3} title="No runs yet" description="Each finished run adds a dot here, with its score, cost and time." />
  {:else}
    <div class="sky-etrend__legend" aria-label="How to read this">
      <span><svg width="22" height="10" viewBox="0 0 22 10" aria-hidden="true"><path d="M1 8L8 4L14 6L21 2" /></svg>One line per verifier model, named at its end</span>
      <span><span class="sky-etrend__legend-dot" aria-hidden="true"></span>One dot per run</span>
      <span>Top: quality score from the judge. Bottom: what each run cost you.</span>
      <span>Hover a dot for the run.</span>
    </div>

    <ul class="sky-etrend__cards" aria-label={`Each verifier: latest score and ${model.metric.label.toLowerCase()}`}>
      {#each model.cards as c (c.key)}
        <li class="sky-etrend__card" aria-label={c.label}>
          <span class="sky-etrend__card-name"><span class="sky-etrend__swatch" data-color={c.color} aria-hidden="true"></span>{c.model}</span>
          <div class="sky-etrend__card-figs">
            <span class="sky-etrend__fig">
              <span class="sky-etrend__fig-label">Score</span>
              <span class="sky-etrend__fig-value">{c.score}<small>/100</small></span>
              <span class="sky-etrend__delta" data-tone={c.scoreTone}><svg width="11" height="11" viewBox="0 0 16 16" aria-hidden="true"><path d={ARROW[c.scoreDir]} /></svg>{c.scoreDelta}</span>
            </span>
            <span class="sky-etrend__fig">
              <span class="sky-etrend__fig-label">{c.metricLabel}</span>
              <span class="sky-etrend__fig-value">{c.metricValue}</span>
              <span class="sky-etrend__delta" data-tone={c.metricTone}><svg width="11" height="11" viewBox="0 0 16 16" aria-hidden="true"><path d={ARROW[c.metricDir]} /></svg>{c.metricDelta}</span>
            </span>
          </div>
          <span class="sky-etrend__verdict" data-tone={c.tone}>{c.verdict}</span>
        </li>
      {/each}
    </ul>

    <div class="sky-etrend__main">
      <div class="sky-etrend__charts">
        <span class="sky-etrend__caption">
          <strong>Quality score</strong><span>0 to 100</span>
          <span class="sky-etrend__judge"><svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true"><path d={JUDGE} /></svg>judge <code>{model.judges}</code></span>
        </span>
        <TrendChart
          aria-label="Quality score by run"
          role="group"
          lines={model.quality.lines}
          dots={model.quality.dots}
          ends={model.quality.ends}
          yTicks={model.quality.ticks}
          notes={model.notes}
          noteLabels
          threshold={{ top: model.quality.pass, label: `pass ${PASS_SCORE}` }}
          viewHeight={200}
          selected={sel}
          hair={readout?.x ?? null}
          onpick={pick}
        />
        <div class="sky-etrend__metric">
          <span class="sky-etrend__caption"><strong>{model.metric.label}</strong> · {model.metric.unit}</span>
          <ToggleGroup type="single" variant="segmented" aria-label="Efficiency metric" items={METRICS} value={[metric]} onValueChange={(v) => (metric = (v[0] as TrendMetric | undefined) ?? 'cost')} />
        </div>
        <TrendChart
          aria-label={`${model.metric.label} by run`}
          role="group"
          size="md"
          lines={model.efficiency.lines}
          dots={model.efficiency.dots}
          ends={model.efficiency.ends}
          yTicks={model.efficiency.ticks}
          xTicks={model.xTicks}
          notes={model.notes}
          viewHeight={150}
          selected={sel}
          hair={readout?.x ?? null}
          onpick={pick}
        />
      </div>

      {#if readout}
        <div class="sky-etrend__readout" role="status" aria-live="polite">
          <div class="sky-etrend__readout-top">
            <span class="sky-etrend__eyebrow">Run</span>
            <span class="sky-etrend__steps">
              <button type="button" aria-label="Previous run" onclick={() => pick(stepRun(model, sel, -1))}><svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3.5L5.5 8 10 12.5" /></svg></button>
              <button type="button" aria-label="Next run" onclick={() => pick(stepRun(model, sel, 1))}><svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5" /></svg></button>
            </span>
          </div>
          <div class="sky-etrend__who">
            <span class="sky-etrend__date">{readout.date}</span>
            <span class="sky-etrend__model"><span class="sky-etrend__swatch" data-color={readout.color} aria-hidden="true"></span>{readout.model}</span>
          </div>
          <div class="sky-etrend__score">
            <span class="sky-etrend__score-row">
              <span><span class="sky-etrend__score-value">{readout.score}</span> <span class="sky-etrend__score-of">{readout.scoreOf}</span></span>
              <span class="sky-etrend__pill" data-verdict={readout.verdict}>{readout.verdictWord}</span>
            </span>
            <span class="sky-etrend__judged"><svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true"><path d={JUDGE} /></svg>Judged by <code>{readout.judge}</code></span>
          </div>
          <dl class="sky-etrend__figs">
            <div><dt>Cost</dt><dd>{readout.cost}</dd></div>
            <div><dt>Speed</dt><dd>{readout.speed}</dd></div>
            <div><dt>Tokens</dt><dd>{readout.tokens}</dd></div>
          </dl>
          {#if readout.executionId}
            <a class="sky-etrend__open" href={href(`/executions/${encodeURIComponent(readout.executionId)}`)}>Open this run <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5" /></svg></a>
          {/if}
        </div>
      {/if}
    </div>

    <div class="sky-etrend__lanes">
      <div class="sky-etrend__lanes-head">
        <span class="sky-etrend__eyebrow">Verdicts</span>
        <span class="sky-etrend__keys">
          <span><span class="sky-etrend__key" data-verdict="pass" aria-hidden="true"></span>Pass</span>
          <span><span class="sky-etrend__key" data-verdict="fail" aria-hidden="true"></span>Fail</span>
          <span><span class="sky-etrend__key" data-verdict="error" aria-hidden="true"></span>Error</span>
          <span><span class="sky-etrend__key" data-verdict="unscored" aria-hidden="true"></span>Unscored</span>
        </span>
      </div>
      {#each model.lanes as lane (lane.key)}
        <div class="sky-etrend__lane">
          <span class="sky-etrend__swatch" data-color={lane.color} aria-hidden="true"></span>
          <div class="sky-etrend__track" role="group" aria-label={`${lane.model} verdicts`}>
            {#each lane.ticks as k (k.i)}
              <button type="button" aria-label={k.label} aria-pressed={k.i === sel} style:left={`${k.x}%`} onpointerenter={() => pick(k.i)} onfocus={() => pick(k.i)} onclick={() => pick(k.i)}>
                <span data-verdict={k.verdict}></span>
              </button>
            {/each}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</section>

<style>
  .sky-etrend {
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
  [data-color='1'] {
    --sky-trend-c: var(--sky-color-series-1);
  }
  [data-color='2'] {
    --sky-trend-c: var(--sky-color-series-2);
  }
  [data-color='3'] {
    --sky-trend-c: var(--sky-color-series-3);
  }
  [data-color='4'] {
    --sky-trend-c: var(--sky-color-series-4);
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
  .sky-etrend__head {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--ds-space-3) var(--ds-space-6);
  }
  .sky-etrend__titles {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    flex: 1 1 20rem;
    min-width: 0;
  }
  .sky-etrend__titles h2 {
    margin: 0;
    font-size: var(--ds-text-lg);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
  }
  .sky-etrend__titles > span {
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-etrend__agent {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--ds-space-1);
  }
  .sky-etrend__agent code {
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
    overflow-wrap: anywhere;
  }
  .sky-etrend__legend {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1-5) var(--ds-space-4);
    padding: var(--ds-space-2-5) var(--ds-space-3-5);
    border-radius: var(--sky-radius-control);
    background: var(--ds-color-bg);
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
  .sky-etrend__legend > span {
    display: flex;
    align-items: center;
    gap: var(--ds-space-1-5);
  }
  .sky-etrend__legend svg path {
    stroke: var(--sky-color-text-code);
    stroke-width: 2;
  }
  .sky-etrend__legend-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--sky-color-text-code);
  }
  .sky-etrend__cards {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--ds-space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-etrend__card {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
    min-width: 0;
    padding: var(--ds-space-3) var(--ds-space-3-5);
    border-radius: var(--sky-radius-row);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-bg);
  }
  .sky-etrend__card-name,
  .sky-etrend__model {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    min-width: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--sky-color-text-code);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-etrend__swatch {
    flex-shrink: 0;
    width: 16px;
    height: 3px;
    border-radius: 2px;
    background: var(--sky-trend-c);
  }
  .sky-etrend__card-figs {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: var(--ds-space-3);
  }
  .sky-etrend__fig {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    min-width: 0;
  }
  .sky-etrend__fig-label {
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-etrend__fig-value {
    font-size: var(--ds-text-2xl);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums;
  }
  .sky-etrend__fig-value small {
    margin-left: 3px;
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-regular);
    letter-spacing: 0;
    color: var(--ds-color-text-subtle);
  }
  .sky-etrend__delta {
    display: flex;
    align-items: center;
    gap: var(--ds-space-1);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
    white-space: nowrap;
  }
  .sky-etrend__delta[data-tone='good'],
  .sky-etrend__verdict[data-tone='good'] {
    color: var(--sky-color-success-soft-fg);
  }
  .sky-etrend__delta[data-tone='bad'],
  .sky-etrend__verdict[data-tone='bad'] {
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-etrend__verdict {
    align-self: flex-start;
    height: 1.375rem;
    padding: 0 9px;
    border-radius: var(--ds-radius-full);
    background: var(--sky-color-neutral-soft);
    color: var(--ds-color-text-muted);
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-semibold);
    line-height: 1.375rem;
  }
  .sky-etrend__verdict[data-tone='good'] {
    background: var(--sky-color-success-soft);
  }
  .sky-etrend__verdict[data-tone='bad'] {
    background: var(--sky-color-danger-soft);
  }
  .sky-etrend__main {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    min-width: 0;
  }
  .sky-etrend__charts {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
    flex: 1 1 auto;
    min-width: 0;
  }
  .sky-etrend__caption {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1-5) var(--ds-space-2-5);
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
  .sky-etrend__caption strong {
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
  }
  .sky-etrend__judge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: 1.375rem;
    padding: 0 9px;
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-border-muted);
    background: var(--ds-color-surface-raised);
    color: var(--sky-color-text-code);
  }
  .sky-etrend__judge code,
  .sky-etrend__judged code {
    color: var(--ds-color-fg);
  }
  .sky-etrend__metric {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-2) var(--ds-space-4);
    margin-top: var(--ds-space-1-5);
  }
  .sky-etrend__readout {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    padding: var(--ds-space-4);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-bg);
  }
  .sky-etrend__readout-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-2);
  }
  .sky-etrend__eyebrow {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-etrend__steps {
    display: flex;
    gap: var(--ds-space-1);
  }
  .sky-etrend__steps button {
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
  .sky-etrend__steps button:hover {
    background: var(--sky-color-control-hover);
  }
  .sky-etrend__steps button:focus-visible,
  .sky-etrend__track button:focus-visible,
  .sky-etrend__open:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-etrend__who {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
  }
  .sky-etrend__date {
    font-size: var(--ds-text-md);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-etrend__score {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    padding: var(--ds-space-3);
    border-radius: var(--sky-radius-control);
    background: var(--ds-color-surface);
  }
  .sky-etrend__score-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-2);
  }
  .sky-etrend__score-value {
    font-size: var(--sky-text-3xl);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums;
  }
  .sky-etrend__score-of {
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-etrend__pill {
    flex-shrink: 0;
    height: 1.5rem;
    padding: 0 11px;
    border-radius: var(--ds-radius-full);
    background: var(--sky-color-neutral-soft);
    color: var(--ds-color-text-muted);
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-semibold);
    line-height: 1.5rem;
  }
  .sky-etrend__pill[data-verdict='pass'] {
    background: var(--sky-color-accent-soft);
    color: var(--sky-color-accent-soft-fg);
  }
  .sky-etrend__pill[data-verdict='fail'] {
    background: var(--sky-color-danger-soft);
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-etrend__pill[data-verdict='error'] {
    background: var(--sky-color-warning-soft);
    color: var(--sky-color-warning-soft-fg);
  }
  .sky-etrend__judged {
    display: flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-etrend__judged svg {
    color: var(--sky-color-text-code);
  }
  .sky-etrend__figs {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--ds-space-2);
    margin: 0;
  }
  .sky-etrend__figs div {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
  }
  .sky-etrend__figs dt {
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-etrend__figs dd {
    margin: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-sm);
  }
  .sky-etrend__open {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
    text-decoration: none;
  }
  .sky-etrend__lanes {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1-5);
    padding-top: var(--ds-space-3-5);
    border-top: var(--ds-border-width) solid var(--ds-color-border);
  }
  .sky-etrend__lanes-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1-5) var(--ds-space-3-5);
  }
  .sky-etrend__keys {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-1-5) var(--ds-space-3);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-etrend__keys > span {
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .sky-etrend__key,
  .sky-etrend__track span {
    width: 8px;
    border-radius: 2px;
    background: var(--sky-color-unscored);
    height: 3px;
  }
  [data-verdict='pass'].sky-etrend__key,
  .sky-etrend__track span[data-verdict='pass'] {
    height: 14px;
    background: var(--ds-color-accent);
  }
  [data-verdict='fail'].sky-etrend__key,
  .sky-etrend__track span[data-verdict='fail'] {
    height: 7px;
    background: var(--ds-color-danger);
  }
  [data-verdict='error'].sky-etrend__key,
  .sky-etrend__track span[data-verdict='error'] {
    height: 7px;
    background: var(--ds-color-warning);
  }
  .sky-etrend__lane {
    display: grid;
    grid-template-columns: 2.5rem minmax(0, 1fr);
    column-gap: var(--ds-space-2);
    align-items: end;
  }
  .sky-etrend__lane > .sky-etrend__swatch {
    justify-self: end;
    margin-bottom: var(--ds-space-1);
  }
  .sky-etrend__track {
    position: relative;
    height: 1.375rem;
    border-bottom: var(--ds-border-width) solid var(--ds-color-border);
  }
  .sky-etrend__track button {
    position: absolute;
    bottom: 0;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    width: 18px;
    height: 1.375rem;
    margin-left: -9px;
    padding: 0 0 1px;
    border: 0;
    background: transparent;
    cursor: pointer;
  }
  .sky-etrend__track button[aria-pressed='true'] span {
    box-shadow:
      0 0 0 2px var(--ds-color-surface),
      0 0 0 3px var(--ds-color-fg);
  }
  @media (min-width: 48rem) {
    .sky-etrend {
      padding: var(--ds-space-6);
    }
    .sky-etrend__titles h2 {
      font-size: var(--ds-text-xl);
    }
    .sky-etrend__titles > span {
      font-size: var(--ds-text-md);
    }
    .sky-etrend__agent {
      align-items: flex-end;
    }
    .sky-etrend__cards {
      grid-template-columns: repeat(auto-fit, minmax(13.75rem, 1fr));
      gap: var(--ds-space-2-5);
    }
    .sky-etrend__card {
      padding: var(--ds-space-3-5) var(--ds-space-4);
    }
    .sky-etrend__lane {
      grid-template-columns: 3rem minmax(0, 1fr);
    }
  }
  @media (min-width: 64rem) {
    .sky-etrend__main {
      flex-direction: row;
      align-items: stretch;
    }
    .sky-etrend__readout {
      flex: 0 0 16rem;
      align-self: flex-start;
    }
    .sky-etrend__steps button {
      width: 1.875rem;
      height: 1.875rem;
    }
  }
  @media (min-width: 64rem) and (pointer: coarse) {
    .sky-etrend__steps button {
      width: var(--sky-size-touch);
      height: var(--sky-size-touch);
    }
  }
</style>
