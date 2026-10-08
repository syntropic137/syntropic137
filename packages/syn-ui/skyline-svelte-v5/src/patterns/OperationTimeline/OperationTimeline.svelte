<!--
  Operation Timeline (Session board, CompPatterns): one row per tool call
  with its time, a tool glyph on a rail, the input on one line and the
  output beneath. Input and output each have a Copy Button; failures are
  coral. Long outputs fold. On a phone the time moves above the row and
  commands wrap instead of truncating. Filters and Copy all belong to the
  screen (use operationsToText()).
-->
<script lang="ts">
  import { SvelteSet } from 'svelte/reactivity'
  import { OUTPUT_PREVIEW_LINES, foldOutput, operationStatusText, toolGlyph } from '@syn137/skyline-core/patterns'
  import CopyButton from '../CopyButton/CopyButton.svelte'
  import Glyph from '../Glyph/Glyph.svelte'
  import type { OperationTimelineProps } from './types'

  let { operations, previewLines = OUTPUT_PREVIEW_LINES, expanded = false, ...rest }: OperationTimelineProps = $props()

  const open = new SvelteSet<string>()
  const toggle = (id: string) => (open.has(id) ? open.delete(id) : open.add(id))
</script>

<ol {...rest} class="sky-ops">
  {#each operations as op (op.id)}
    {@const fold = op.output ? foldOutput(op.output, previewLines) : null}
    {@const unfolded = expanded || open.has(op.id)}
    <li class="sky-ops__op" data-status={op.status}>
      <span class="sky-ops__time">{op.time}</span>
      <span class="sky-ops__rail" aria-hidden="true">
        <span class="sky-ops__badge"><Glyph d={toolGlyph(op.tool)} size={14} weight={1.7} /></span>
        <span class="sky-ops__line"></span>
      </span>
      <div class="sky-ops__body">
        <div class="sky-ops__head">
          <span class="sky-ops__tool">{op.tool}</span>
          <code class="sky-ops__input">{op.input}</code>
          {#if operationStatusText(op)}<span class="sky-ops__status">{operationStatusText(op)}</span>{/if}
          <CopyButton text={op.input} label={`Copy the ${op.tool} input`} copiedLabel={`Copied the ${op.tool} input`} />
        </div>
        {#if op.delegated}
          <svelte:element this={op.delegated.href ? 'a' : 'span'} class="sky-ops__delegated" href={op.delegated.href}>
            <span class="sky-ops__agent-dot" data-agent={op.delegated.agentKind ?? 'other'}></span>
            <span>{op.delegated.label}{#if op.delegated.id}&nbsp;<span class="sky-ops__mono">{op.delegated.id}</span>{/if}{#if op.delegated.href}&nbsp;→{/if}</span>
          </svelte:element>
        {/if}
        {#if fold}
          <div class="sky-ops__output">
            <pre class="sky-ops__pre">{unfolded ? op.output : fold.preview}</pre>
            <span class="sky-ops__copy-out"><CopyButton text={op.output ?? ''} label="Copy the output" copiedLabel="Copied the output" /></span>
            {#if fold.hidden > 0 && !expanded}
              <button class="sky-ops__more" type="button" aria-expanded={unfolded} onclick={() => toggle(op.id)}>
                {unfolded ? 'Show less' : `Show ${fold.hidden} more ${fold.hidden === 1 ? 'line' : 'lines'}`}
              </button>
            {/if}
          </div>
        {/if}
      </div>
    </li>
  {/each}
</ol>

<style>
  .sky-ops {
    container-type: inline-size;
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-ops__op {
    --_tone: var(--ds-color-accent);
    --_badge: var(--sky-color-accent-soft);
    display: grid;
    grid-template-columns: 1.875rem minmax(0, 1fr);
    grid-template-areas:
      'time time'
      'rail body';
    column-gap: var(--ds-space-3);
  }
  .sky-ops__op[data-status='failed'] {
    --_tone: var(--ds-color-danger);
    --_badge: var(--sky-color-danger-soft);
  }
  .sky-ops__op[data-status='quiet'] {
    --_tone: var(--ds-color-text-muted);
    --_badge: var(--sky-color-neutral-soft);
  }
  .sky-ops__time {
    grid-area: time;
    padding-bottom: var(--ds-space-1);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
    white-space: nowrap;
  }
  .sky-ops__rail {
    grid-area: rail;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--ds-space-1);
  }
  .sky-ops__badge {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 1.875rem;
    height: 1.875rem;
    border-radius: var(--ds-radius-md);
    background: var(--_badge);
    color: var(--_tone);
  }
  .sky-ops__line {
    flex-grow: 1;
    width: 2px;
    border-radius: 1px;
    background: var(--ds-color-border);
  }
  .sky-ops__op:last-child .sky-ops__line {
    visibility: hidden;
  }
  .sky-ops__body {
    grid-area: body;
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
    padding-bottom: var(--ds-space-5);
  }
  .sky-ops__head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1) var(--ds-space-2-5);
    min-width: 0;
    min-height: 1.875rem;
  }
  .sky-ops__tool {
    flex-shrink: 0;
    font-size: var(--ds-text-md);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-ops__input {
    order: 5;
    flex: 1 0 100%;
    min-width: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    color: var(--sky-color-text-code);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .sky-ops__status {
    flex-shrink: 0;
    margin-left: auto;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-ops__op[data-status='failed'] .sky-ops__status {
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-ops__delegated {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-2);
    align-self: flex-start;
    min-height: 1.875rem;
    padding: 0 var(--ds-space-3);
    border-radius: var(--ds-radius-full);
    background: color-mix(in oklab, var(--sky-color-agent-claude) 18%, transparent);
    color: var(--ds-color-fg);
    font-size: var(--sky-text-data);
    text-decoration: none;
  }
  .sky-ops__delegated:focus-visible,
  .sky-ops__more:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-ops__agent-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--ds-color-text-subtle);
  }
  .sky-ops__agent-dot[data-agent='claude'] {
    background: var(--sky-color-agent-claude);
  }
  .sky-ops__agent-dot[data-agent='codex'] {
    background: var(--sky-color-agent-codex);
  }
  .sky-ops__mono {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
  }
  .sky-ops__output {
    position: relative;
    display: flex;
    flex-direction: column;
  }
  .sky-ops__pre {
    margin: 0;
    padding: var(--ds-space-2-5) 2.75rem var(--ds-space-2-5) var(--ds-space-3-5);
    border-radius: var(--sky-radius-control);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-bg);
    color: var(--ds-color-text-muted);
    font-family: var(--ds-font-mono);
    font-size: 0.75rem;
    line-height: 1.5;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .sky-ops__op[data-status='failed'] .sky-ops__pre {
    border-color: color-mix(in oklab, var(--ds-color-danger) 28%, var(--ds-color-bg));
    background: color-mix(in oklab, var(--ds-color-danger) 9%, var(--ds-color-bg));
    color: color-mix(in oklab, var(--ds-color-danger) 50%, var(--ds-color-fg));
  }
  .sky-ops__copy-out {
    position: absolute;
    top: 5px;
    right: 6px;
  }
  .sky-ops__more {
    align-self: flex-start;
    min-height: var(--sky-size-control-sm);
    margin-top: var(--ds-space-1);
    padding: 0 var(--ds-space-2);
    border: 0;
    border-radius: var(--ds-radius-md);
    background: transparent;
    color: var(--ds-color-text-muted);
    font: inherit;
    font-size: var(--sky-text-data);
    cursor: pointer;
  }
  .sky-ops__more:hover {
    background: var(--sky-color-control-hover);
    color: var(--ds-color-fg);
  }

  @container (min-width: 36rem) {
    .sky-ops__op {
      grid-template-columns: 4.875rem 1.875rem minmax(0, 1fr);
      grid-template-areas: 'time rail body';
      column-gap: var(--ds-space-3-5);
    }
    .sky-ops__time {
      padding-top: 7px;
      padding-bottom: 0;
    }
    .sky-ops__head {
      flex-wrap: nowrap;
    }
    .sky-ops__input {
      order: 0;
      flex: 1 1 auto;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .sky-ops__status {
      margin-left: 0;
    }
  }
  @media (pointer: coarse) {
    .sky-ops__more,
    .sky-ops__delegated {
      min-height: var(--sky-size-touch);
    }
  }
</style>
