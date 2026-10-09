<!--
  Verdict Board (Evals board): cases down the side, verifiers across, one
  Verdict Block per run, then bugs caught with average cost and time per
  verifier. Pointing at, focusing or clicking a cell shows it in the
  readout; arrow keys move between cells. Column heads abbreviate and the
  readout drops under the board in narrow containers.
-->
<script lang="ts">
  import { tick } from 'svelte'
  import { formatCost, formatDuration } from '@syn137/skyline-core/format'
  import { VERDICT_LOOK, cellKey, verdictCellLabel, verifierFooter } from '@syn137/skyline-core/patterns'
  import { gridCursor, gridKey } from '@syn137/skyline-core/state'
  import VerdictBlock from '../VerdictBlock/VerdictBlock.svelte'
  import type { VerdictBoardProps } from './types'

  let {
    title = 'Verdict board',
    suite,
    description,
    cases,
    verifiers,
    cells,
    selected = $bindable(null),
    onselect,
    ...rest
  }: VerdictBoardProps = $props()

  let grid: HTMLDivElement | undefined = $state()

  const pos = $derived.by(() => {
    for (let r = 0; r < cases.length; r++)
      for (let c = 0; c < verifiers.length; c++) if (cellKey(cases[r]!.id, verifiers[c]!.id) === selected) return { row: r, col: c }
    return { row: 0, col: 0 }
  })
  const pickCase = $derived(cases[pos.row])
  const pickVerifier = $derived(verifiers[pos.col])
  const pick = $derived(pickCase && pickVerifier ? cells[cellKey(pickCase.id, pickVerifier.id)] : undefined)
  const footers = $derived(verifiers.map((v) => verifierFooter(cases.map((c) => cells[cellKey(c.id, v.id)]))))

  async function select(row: number, col: number, focus = false) {
    const c = cases[row]
    const v = verifiers[col]
    if (!c || !v) return
    const key = cellKey(c.id, v.id)
    if (key !== selected) {
      selected = key
      onselect?.(c.id, v.id)
    }
    if (focus) {
      await tick()
      grid?.querySelector<HTMLButtonElement>(`[data-cell="${CSS.escape(key)}"]`)?.focus()
    }
  }

  function onkey(e: KeyboardEvent) {
    const ev = gridKey(e.key, e.ctrlKey || e.metaKey)
    if (!ev) return
    e.preventDefault()
    const next = gridCursor({ ...pos, rows: cases.length, cols: verifiers.length }, ev)
    void select(next.row, next.col, true)
  }
</script>

<section {...rest} class="sky-verdicts" aria-label={rest['aria-label'] ?? title}>
  <header class="sky-verdicts__head">
    <div class="sky-verdicts__intro">
      <div class="sky-verdicts__title-row">
        <h2 class="sky-verdicts__title">{title}</h2>
        {#if suite}<span class="sky-verdicts__suite">{suite}</span>{/if}
      </div>
      {#if description}<p class="sky-verdicts__description">{description}</p>{/if}
    </div>
    <ul class="sky-verdicts__legend" aria-label="Legend">
      {#each Object.entries(VERDICT_LOOK) as [key, look] (key)}
        <li><span class="sky-verdicts__key" data-verdict={key}></span>{look.label}</li>
      {/each}
    </ul>
  </header>

  <div class="sky-verdicts__body">
    <div class="sky-verdicts__scroll">
      <div
        class="sky-verdicts__grid"
        role="grid"
        aria-label="Latest verdict for each case under each verifier"
        bind:this={grid}
        style:--cols={verifiers.length}
      >
        <div class="sky-verdicts__row sky-verdicts__row--head" role="row">
          <span class="sky-verdicts__corner" role="columnheader">Case</span>
          {#each verifiers as v (v.id)}
            <span class="sky-verdicts__col" role="columnheader">
              <span class="sky-verdicts__agent"><span class="sky-verdicts__dot" data-agent={v.agentKind ?? 'other'}></span>{v.agent}</span>
              <span class="sky-verdicts__model">
                <span class="sky-verdicts__model-full">{v.model}</span>
                <span class="sky-verdicts__model-short" aria-hidden="true">{v.short ?? v.model}</span>
              </span>
            </span>
          {/each}
        </div>
        {#each cases as c, r (c.id)}
          <div class="sky-verdicts__row" role="row">
            <span class="sky-verdicts__case" role="rowheader">
              <span class="sky-verdicts__case-name">{c.name}</span>
              {#if c.sub}<span class="sky-verdicts__case-sub">{c.sub}</span>{/if}
            </span>
            {#each verifiers as v, col (v.id)}
              {@const key = cellKey(c.id, v.id)}
              {@const cell = cells[key]}
              {@const on = r === pos.row && col === pos.col}
              <span class="sky-verdicts__cell" role="gridcell">
                <button
                  class="sky-verdicts__button"
                  type="button"
                  data-cell={key}
                  aria-label={verdictCellLabel(c, v, cell)}
                  aria-pressed={on}
                  tabindex={on ? 0 : -1}
                  onfocus={() => select(r, col)}
                  onclick={() => select(r, col)}
                  onkeydown={onkey}
                >
                  {#if cell}
                    <VerdictBlock verdict={cell.verdict} size={56} />
                    <span class="sky-verdicts__cost">{typeof cell.costUsd === 'number' ? formatCost(cell.costUsd) : '—'}</span>
                  {:else}
                    <span class="sky-verdicts__none">no run</span>
                  {/if}
                </button>
              </span>
            {/each}
          </div>
        {/each}
        <div class="sky-verdicts__row sky-verdicts__row--foot" role="row">
          <span class="sky-verdicts__case" role="rowheader">
            <span class="sky-verdicts__foot-title">Bugs caught</span>
            <span class="sky-verdicts__foot-sub">with average cost and time per case</span>
          </span>
          {#each footers as f, i (i)}
            <span class="sky-verdicts__foot" role="gridcell">
              <span class="sky-verdicts__fraction" data-scored={f.scored || undefined}>{f.fraction}</span>
              <span class="sky-verdicts__meter" aria-hidden="true"><span style:width={`${f.fill}%`}></span></span>
              <span class="sky-verdicts__note">{f.note}</span>
              <span class="sky-verdicts__avg">{f.averages}</span>
            </span>
          {/each}
        </div>
      </div>
    </div>

    <aside class="sky-verdicts__readout" aria-label="Selected run" role="status" aria-live="polite">
      {#if pickCase && pickVerifier}
        {@const look = pick ? VERDICT_LOOK[pick.verdict] : null}
        <div class="sky-verdicts__readout-head">
          <span class="sky-verdicts__pill" data-tone={look?.tone ?? 'unscored'}>{look?.word ?? 'No run'}</span>
          {#if pick?.date}<span class="sky-verdicts__date">{pick.date}</span>{/if}
        </div>
        <div class="sky-verdicts__who">
          <span class="sky-verdicts__pick-name">{pickCase.name}</span>
          <span class="sky-verdicts__pick-agent">
            <span class="sky-verdicts__agent"><span class="sky-verdicts__dot" data-agent={pickVerifier.agentKind ?? 'other'}></span>{pickVerifier.agent}</span>
            <span class="sky-verdicts__pick-model">{pickVerifier.model}</span>
          </span>
          {#if pickVerifier.workflow}<span class="sky-verdicts__pick-wf">{pickVerifier.workflow}</span>{/if}
        </div>
        {#if pick?.evidence}
          <div class="sky-verdicts__evidence">
            <span class="sky-verdicts__label">Scorer evidence</span>
            <p>{pick.evidence}</p>
          </div>
        {/if}
        <dl class="sky-verdicts__stats">
          <div><dt>Cost</dt><dd>{typeof pick?.costUsd === 'number' ? formatCost(pick.costUsd) : '—'}</dd></div>
          <div><dt>Duration</dt><dd>{typeof pick?.durationMs === 'number' ? formatDuration(pick.durationMs) : '—'}</dd></div>
          <div><dt>Runs</dt><dd>{pick?.runs ?? (pick ? 1 : 0)}</dd></div>
        </dl>
        {#if pick?.evalHref || pick?.runHref}
          <div class="sky-verdicts__actions">
            {#if pick.evalHref}<a class="sky-verdicts__action" data-variant="solid" href={pick.evalHref}>Open eval</a>{/if}
            {#if pick.runHref}<a class="sky-verdicts__action" href={pick.runHref}>Open run</a>{/if}
          </div>
        {/if}
      {/if}
    </aside>
  </div>
</section>

<style>
  .sky-verdicts {
    container-type: inline-size;
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    padding: var(--ds-space-5) var(--ds-space-4);
    border-radius: var(--sky-radius-card-lg);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background:
      radial-gradient(60% 60% at 40% 100%, color-mix(in oklab, var(--ds-color-accent) 10%, transparent), transparent 75%),
      var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  @media (min-width: 48rem) {
    .sky-verdicts {
      padding: var(--ds-space-6) var(--ds-space-6) var(--ds-space-5);
    }
  }
  .sky-verdicts__head {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--ds-space-3) var(--ds-space-8);
  }
  .sky-verdicts__intro {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
    max-width: 47.5rem;
  }
  .sky-verdicts__title-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2-5);
  }
  .sky-verdicts__title {
    margin: 0;
    font-size: var(--ds-text-xl);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
  }
  .sky-verdicts__suite {
    height: 1.5rem;
    padding: 0 var(--ds-space-2-5);
    border-radius: var(--ds-radius-full);
    background: color-mix(in oklab, var(--ds-color-accent) 14%, transparent);
    color: var(--sky-color-accent-soft-fg);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    line-height: 1.5rem;
  }
  .sky-verdicts__description {
    margin: 0;
    font-size: var(--ds-text-md);
    line-height: 1.5;
    color: var(--ds-color-text-muted);
    text-wrap: pretty;
  }
  .sky-verdicts__legend {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1-5) var(--ds-space-4);
    margin: 0;
    padding: 0;
    list-style: none;
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
  .sky-verdicts__legend li {
    display: flex;
    align-items: center;
    gap: 7px;
  }
  .sky-verdicts__key {
    width: 10px;
    height: 16px;
    border-radius: 2px;
    background: var(--ds-color-accent);
  }
  .sky-verdicts__key[data-verdict='fail'] {
    height: 8px;
    background: var(--ds-color-danger);
  }
  .sky-verdicts__key[data-verdict='error'] {
    height: 8px;
    background: var(--ds-color-warning);
  }
  .sky-verdicts__key[data-verdict='unscored'] {
    height: 3px;
    border-radius: 1px;
    background: var(--ds-color-text-subtle);
  }

  .sky-verdicts__body {
    display: flex;
    flex-wrap: wrap;
    align-items: stretch;
    gap: var(--ds-space-5) var(--ds-space-6);
  }
  .sky-verdicts__scroll {
    flex: 999 1 40rem;
    min-width: 0;
    overflow-x: auto;
  }
  .sky-verdicts__grid {
    display: flex;
    flex-direction: column;
    min-width: calc(7rem + var(--cols) * 4rem);
  }
  .sky-verdicts__row {
    display: grid;
    grid-template-columns: minmax(7rem, 1.2fr) repeat(var(--cols), minmax(3.75rem, 1fr));
    align-items: center;
    border-bottom: var(--ds-border-width) solid var(--sky-color-divider);
  }
  .sky-verdicts__row--head {
    align-items: end;
    padding-bottom: var(--ds-space-2-5);
    border-bottom-color: var(--ds-color-border);
  }
  .sky-verdicts__row--foot {
    align-items: start;
    padding-top: var(--ds-space-3-5);
    border-bottom: 0;
  }
  .sky-verdicts__corner,
  .sky-verdicts__label,
  .sky-verdicts__stats dt {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-verdicts__corner {
    padding-left: var(--ds-space-1);
  }
  .sky-verdicts__col {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    min-width: 0;
    padding: 0 var(--ds-space-1-5);
    text-align: center;
  }
  .sky-verdicts__agent {
    display: flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    font-size: 0.75rem;
    color: var(--ds-color-text-muted);
  }
  .sky-verdicts__dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--ds-color-text-subtle);
  }
  .sky-verdicts__dot[data-agent='claude'] {
    background: var(--sky-color-agent-claude);
  }
  .sky-verdicts__dot[data-agent='codex'] {
    background: var(--sky-color-agent-codex);
  }
  .sky-verdicts__model {
    max-width: 100%;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    font-weight: var(--ds-font-weight-semibold);
    overflow-wrap: anywhere;
  }
  /* Narrow: the short name shows, the full name stays for screen readers. */
  .sky-verdicts__model-full {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
  .sky-verdicts__case {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    padding: var(--ds-space-2) var(--ds-space-1);
  }
  .sky-verdicts__case-name {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    font-weight: var(--ds-font-weight-semibold);
    overflow-wrap: anywhere;
  }
  .sky-verdicts__case-sub {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-verdicts__cell {
    display: flex;
    min-width: 0;
  }
  .sky-verdicts__button {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-end;
    flex-grow: 1;
    min-width: 0;
    min-height: 4.25rem;
    margin: var(--ds-space-1);
    padding: 6px var(--ds-space-1) var(--ds-space-2);
    border-radius: var(--sky-radius-row);
    border: var(--ds-border-width) solid transparent;
    background: transparent;
    color: var(--ds-color-text-muted);
    font: inherit;
    cursor: pointer;
  }
  .sky-verdicts__button :global(.sky-verdict-block) {
    width: 2.75rem;
    height: auto;
  }
  .sky-verdicts__button:hover {
    background: var(--sky-color-control-hover);
  }
  .sky-verdicts__button[aria-pressed='true'] {
    border-color: color-mix(in oklab, var(--ds-color-accent) 70%, var(--ds-color-border));
    background: var(--sky-color-control-hover);
    color: var(--ds-color-fg);
  }
  .sky-verdicts__button:focus-visible,
  .sky-verdicts__action:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-verdicts__cost {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
  }
  .sky-verdicts__none {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-verdicts__foot-title {
    font-size: var(--ds-text-md);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-verdicts__foot-sub {
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
  .sky-verdicts__foot {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--ds-space-1-5);
    min-width: 0;
    padding: 0 var(--ds-space-1);
    text-align: center;
  }
  .sky-verdicts__fraction {
    font-size: 1.375rem;
    line-height: 1.1;
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
    color: var(--ds-color-text-subtle);
  }
  .sky-verdicts__fraction[data-scored] {
    color: var(--ds-color-fg);
  }
  .sky-verdicts__meter {
    display: block;
    width: 100%;
    max-width: 6.875rem;
    height: 6px;
    border-radius: 3px;
    background: var(--ds-color-overlay);
  }
  .sky-verdicts__meter span {
    display: block;
    height: 100%;
    border-radius: 3px;
    background: var(--ds-color-accent);
  }
  .sky-verdicts__note {
    font-size: 0.75rem;
    color: var(--ds-color-text-muted);
  }
  .sky-verdicts__avg {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }

  .sky-verdicts__readout {
    flex: 1 1 17.5rem;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3-5);
    padding: var(--ds-space-4);
    border-radius: var(--ds-space-4);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-surface-raised);
    box-shadow: var(--sky-shadow-selected);
  }
  .sky-verdicts__readout-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-2-5);
  }
  .sky-verdicts__pill {
    height: 1.625rem;
    padding: 0 var(--ds-space-3);
    border-radius: var(--ds-radius-full);
    background: var(--sky-color-neutral-soft);
    color: var(--ds-color-text-muted);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
    line-height: 1.625rem;
  }
  .sky-verdicts__pill[data-tone='accent'] {
    background: var(--sky-color-accent-soft);
    color: var(--sky-color-accent-soft-fg);
  }
  .sky-verdicts__pill[data-tone='danger'] {
    background: var(--sky-color-danger-soft);
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-verdicts__pill[data-tone='warning'] {
    background: var(--sky-color-warning-soft);
    color: var(--sky-color-warning-soft-fg);
  }
  .sky-verdicts__date,
  .sky-verdicts__pick-model {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-verdicts__who {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1-5);
    min-width: 0;
  }
  .sky-verdicts__pick-name {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-body);
    font-weight: var(--ds-font-weight-semibold);
    overflow-wrap: anywhere;
  }
  .sky-verdicts__pick-agent {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1-5) var(--ds-space-2);
    font-size: var(--ds-text-sm);
  }
  .sky-verdicts__pick-agent .sky-verdicts__agent {
    font-size: var(--ds-text-sm);
    color: var(--ds-color-fg);
  }
  .sky-verdicts__pick-wf {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
    overflow-wrap: anywhere;
  }
  .sky-verdicts__evidence,
  .sky-verdicts__stats {
    padding-top: var(--ds-space-3-5);
    border-top: var(--ds-border-width) solid var(--sky-color-border-muted);
  }
  .sky-verdicts__evidence {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1-5);
  }
  .sky-verdicts__evidence p {
    margin: 0;
    font-size: var(--ds-text-md);
    line-height: 1.5;
    color: var(--sky-color-text-code);
  }
  .sky-verdicts__stats {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--ds-space-2-5);
    margin: 0;
  }
  .sky-verdicts__stats div {
    display: flex;
    flex-direction: column-reverse;
    gap: 2px;
  }
  .sky-verdicts__stats dd {
    margin: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-body);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-verdicts__actions {
    display: flex;
    gap: var(--ds-space-2);
    margin-top: auto;
  }
  .sky-verdicts__action {
    display: flex;
    align-items: center;
    justify-content: center;
    flex: 1 1 0;
    height: 2.375rem;
    border-radius: var(--sky-radius-control);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--sky-color-control);
    color: var(--ds-color-fg);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
    text-decoration: none;
  }
  .sky-verdicts__action:hover {
    background: var(--sky-color-control-hover);
  }
  .sky-verdicts__action[data-variant='solid'] {
    border-color: transparent;
    background: var(--sky-color-accent-solid);
    color: var(--sky-color-accent-solid-contrast);
    box-shadow: var(--sky-shadow-glow);
  }

  @container (min-width: 40rem) {
    .sky-verdicts__row {
      grid-template-columns: minmax(12.5rem, 1.5fr) repeat(var(--cols), minmax(6.875rem, 1fr));
    }
    .sky-verdicts__grid {
      min-width: calc(12.5rem + var(--cols) * 6.875rem);
    }
    .sky-verdicts__model-full {
      position: static;
      width: auto;
      height: auto;
      overflow: visible;
      clip: auto;
      white-space: normal;
    }
    .sky-verdicts__model-short {
      display: none;
    }
    .sky-verdicts__button :global(.sky-verdict-block) {
      width: 3.5rem;
    }
    .sky-verdicts__case-name {
      font-size: 0.84375rem;
    }
    .sky-verdicts__fraction {
      font-size: 1.625rem;
    }
  }
  @media (pointer: coarse) {
    .sky-verdicts__button,
    .sky-verdicts__action {
      min-height: var(--sky-size-touch);
    }
  }
</style>
