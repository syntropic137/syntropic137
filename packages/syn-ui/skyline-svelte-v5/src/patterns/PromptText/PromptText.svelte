<!-- Prompt Text: a prompt or task as body copy (feedback 525d15c0). Headings are bold labels at the block's own scale,
     lists are lists, code is mono; long text folds behind a toggle. Blocks come from parsePrompt() in skyline-core. -->
<script lang="ts">
  import { inlineSpans, parsePrompt } from '@syn137/skyline-core/screens/prompt'
  import type { PromptTextProps } from './types'

  let { text, clampLines = 0, moreLabel = 'Show more', lessLabel = 'Show less', argument, ...rest }: PromptTextProps = $props()

  const blocks = $derived(parsePrompt(text))
  let open = $state(false)
  let body = $state<HTMLDivElement>()
  let overflows = $state(false)

  $effect(() => {
    void blocks
    if (!body || !clampLines) return
    const el = body
    const measure = () => (overflows = open || el.scrollHeight > el.clientHeight + 1)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  })
</script>

{#snippet spans(t: string)}{#each inlineSpans(t) as s, i (i)}{#if s.kind === 'code'}<code>{s.text}</code>{:else if s.kind === 'strong'}<strong>{s.text}</strong>{:else}{s.text}{/if}{/each}{/snippet}

<div {...rest} class="sky-prompt">
  <div
    class="sky-prompt__body"
    bind:this={body}
    data-state={clampLines ? (open ? 'open' : 'folded') : undefined}
    data-overflows={overflows || undefined}
    style:--sky-prompt-lines={clampLines || undefined}
  >
    {#each blocks as b, k (k)}
      {#if b.kind === 'heading'}
        <p class="sky-prompt__heading">{@render spans(b.text)}</p>
      {:else if b.kind === 'paragraph'}
        <p>{@render spans(b.text)}</p>
      {:else if b.kind === 'list'}
        <svelte:element this={b.ordered ? 'ol' : 'ul'} class="sky-prompt__list">
          {#each b.items as item, j (j)}
            <li>
              {@render spans(item.text)}
              {#if item.items.length}<ul class="sky-prompt__list">{#each item.items as sub, n (n)}<li>{@render spans(sub)}</li>{/each}</ul>{/if}
            </li>
          {/each}
        </svelte:element>
      {:else if b.kind === 'code'}
        <pre class="sky-prompt__code"><code>{b.text}</code></pre>
      {:else if argument}
        {@render argument(b.name)}
      {:else}
        <p><code>{b.name}</code></p>
      {/if}
    {/each}
  </div>
  {#if clampLines && overflows}
    <button type="button" class="sky-prompt__more" aria-expanded={open} onclick={() => (open = !open)}>{open ? lessLabel : moreLabel}</button>
  {/if}
</div>

<style>
  .sky-prompt {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-prompt__body {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
    min-width: 0;
    font-size: inherit;
    font-weight: var(--ds-font-weight-regular);
    line-height: var(--ds-line-height-normal);
    overflow-wrap: anywhere;
  }
  .sky-prompt__body[data-state='folded'] {
    max-height: calc(var(--sky-prompt-lines) * 1lh);
    overflow: hidden;
  }
  .sky-prompt__body[data-state='folded'][data-overflows] {
    mask-image: linear-gradient(to bottom, currentColor 70%, transparent);
  }
  .sky-prompt__body p,
  .sky-prompt__list,
  .sky-prompt__code {
    margin: 0;
  }
  .sky-prompt__heading {
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
  }
  .sky-prompt__list {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
    padding-left: var(--ds-space-5);
  }
  .sky-prompt__list .sky-prompt__list {
    margin-top: var(--ds-space-1);
  }
  .sky-prompt__list li::marker {
    color: var(--ds-color-text-muted);
  }
  .sky-prompt__body code {
    font-family: var(--ds-font-mono);
    font-size: 0.9em;
  }
  .sky-prompt__body :not(pre) > code {
    padding: 0 var(--ds-space-1);
    border-radius: var(--ds-radius-xs);
    background: var(--ds-color-surface-raised);
  }
  .sky-prompt__code {
    padding: var(--ds-space-3);
    border-radius: var(--sky-radius-control);
    background: var(--ds-color-surface-raised);
    overflow-x: auto;
    line-height: var(--ds-line-height-code);
    white-space: pre;
  }
  .sky-prompt__more {
    align-self: flex-start;
    padding: 0;
    border: 0;
    background: none;
    color: var(--sky-color-accent-soft-fg);
    font: inherit;
    font-size: var(--ds-text-sm);
    cursor: pointer;
  }
  .sky-prompt__more:hover {
    color: var(--ds-color-fg);
  }
  .sky-prompt__more:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-prompt__more {
      min-height: var(--sky-size-touch);
    }
  }
</style>
