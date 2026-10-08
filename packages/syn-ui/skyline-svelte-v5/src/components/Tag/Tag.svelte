<!--
  Tag (CompDisplay "Tag and chips"). Accent tags filter when clicked;
  neutral chips only label. A removable filter tag is one button with a
  trailing cross (CompActions "removable tag filter").
-->
<script lang="ts">
  import type { HTMLAnchorAttributes, HTMLButtonAttributes } from 'svelte/elements'
  import Glyph from '../_internal/Glyph.svelte'
  import type { TagProps } from './types'

  let {
    variant = 'outline',
    agent = 'claude',
    href,
    onclick,
    onremove,
    removeLabel,
    icon,
    children,
    ...rest
  }: TagProps = $props()

  const kind = $derived(onremove ? 'remove' : href ? 'link' : onclick ? 'button' : 'static')

  function remove(e: MouseEvent) {
    onclick?.(e)
    if (!e.defaultPrevented) onremove?.()
  }
</script>

{#snippet body()}
  {#if variant === 'skill'}
    <span class="sky-tag__icon sky-tag__icon--accent"><Glyph name="diamond" size={11} strokeWidth={1.75} /></span>
  {:else if variant === 'agent'}
    <span class="sky-tag__dot" data-agent={agent} aria-hidden="true"></span>
  {:else if icon}
    <span class="sky-tag__icon">{@render icon()}</span>
  {/if}
  <span class="sky-tag__text">{#if kind === 'remove' && !removeLabel}<span class="sky-visually-hidden">Remove filter</span>{' '}{/if}{@render children?.()}</span>
  {#if kind === 'remove'}
    <Glyph name="cross" size={12} strokeWidth={1.9} />
  {/if}
{/snippet}

{#if kind === 'link'}
  <a {...rest as HTMLAnchorAttributes} class="sky-tag" {href} data-variant={variant} data-interactive="">{@render body()}</a>
{:else if kind === 'button'}
  <button {...rest as HTMLButtonAttributes} type="button" class="sky-tag" data-variant={variant} data-interactive="" {onclick}>
    {@render body()}
  </button>
{:else if kind === 'remove'}
  <button
    {...rest as HTMLButtonAttributes}
    type="button"
    class="sky-tag"
    data-variant={variant}
    data-interactive=""
    data-removable=""
    aria-label={removeLabel}
    onclick={remove}
  >
    {@render body()}
  </button>
{:else}
  <span {...rest} class="sky-tag" data-variant={variant}>{@render body()}</span>
{/if}

<style>
  .sky-tag {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    box-sizing: border-box;
    max-width: 100%;
    height: 1.25rem; /* 20 */
    padding: 0 var(--ds-space-2);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    border-radius: var(--ds-radius-full);
    background: transparent;
    color: var(--ds-color-text-muted);
    font-family: var(--ds-font-mono);
    font-size: 0.71875rem; /* 11.5 */
    line-height: 1;
    text-decoration: none;
    white-space: nowrap;
    vertical-align: middle;
    -webkit-tap-highlight-color: transparent;
  }
  .sky-tag__text {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-tag__icon {
    display: flex;
  }
  .sky-tag__icon--accent {
    color: var(--ds-color-accent);
  }

  .sky-tag[data-variant='accent'] {
    height: 1.5rem;
    padding: 0 var(--ds-space-2-5);
    border-color: transparent;
    background: color-mix(in oklab, var(--ds-color-accent) 14%, transparent);
    color: color-mix(in oklab, var(--ds-color-accent) 45%, var(--ds-color-fg));
  }
  .sky-tag[data-variant='skill'] {
    height: 1.5rem;
    padding: 0 var(--ds-space-2) 0 var(--ds-space-1-5);
    border-color: var(--sky-color-border-muted);
    border-radius: var(--ds-space-2);
    background: var(--sky-color-control-hover);
    color: var(--sky-color-text-code);
  }
  .sky-tag[data-variant='agent'] {
    gap: var(--ds-space-2);
    height: 1.625rem;
    padding: 0 var(--ds-space-3);
    border-color: transparent;
    background: var(--sky-color-control-hover);
    color: var(--ds-color-fg);
    font-family: var(--ds-font-sans);
    font-size: var(--ds-text-sm);
  }
  .sky-tag[data-variant='dashed'] {
    border-style: dashed;
    border-color: var(--sky-color-border-hover);
    border-radius: 0.4375rem;
    font-size: var(--ds-text-xs);
  }
  .sky-tag__dot {
    flex-shrink: 0;
    width: 0.4375rem;
    height: 0.4375rem;
    border-radius: 50%;
    background: var(--ds-color-text-subtle);
  }
  .sky-tag__dot[data-agent='claude'] {
    background: var(--sky-color-agent-claude);
  }
  .sky-tag__dot[data-agent='codex'] {
    background: var(--sky-color-agent-codex);
  }

  .sky-tag[data-removable] {
    gap: var(--ds-space-2);
    height: 1.75rem;
    padding: 0 var(--ds-space-2) 0 var(--ds-space-3);
    border-color: var(--sky-color-border-hover);
    background: var(--ds-color-overlay);
    color: var(--ds-color-fg);
  }

  .sky-tag[data-interactive] {
    cursor: pointer;
    font-family: var(--ds-font-mono);
  }
  .sky-tag[data-interactive]:hover {
    border-color: var(--sky-color-border-hover);
    color: var(--ds-color-fg);
  }
  .sky-tag[data-variant='accent'][data-interactive]:hover {
    border-color: transparent;
    background: var(--sky-color-accent-ring);
  }
  .sky-tag:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    /* Grow the hit area, not the drawn chip. */
    .sky-tag[data-interactive] {
      position: relative;
    }
    .sky-tag[data-interactive]::after {
      content: '';
      position: absolute;
      inset: 50% auto auto 50%;
      width: max(100%, var(--sky-size-touch));
      height: var(--sky-size-touch);
      transform: translate(-50%, -50%);
    }
  }
</style>
