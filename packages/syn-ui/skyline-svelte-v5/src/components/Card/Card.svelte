<!--
  Card (CompDisplay board). Round and quiet: one hairline, a 1px top
  highlight, 18px radius (24px for the header card).
-->
<script lang="ts">
  import type { CardProps } from './types'

  let {
    variant = 'standard',
    padding = 'md',
    interactive = false,
    selected = false,
    href,
    as = 'div',
    children,
    ...rest
  }: CardProps = $props()
</script>

{#if href}
  <a
    {...rest}
    class="sky-card"
    {href}
    data-variant={variant}
    data-padding={padding}
    data-interactive=""
    data-selected={selected || undefined}
  >
    {@render children?.()}
  </a>
{:else}
  <svelte:element
    this={as}
    {...rest}
    class="sky-card"
    data-variant={variant}
    data-padding={padding}
    data-interactive={interactive || undefined}
    data-selected={selected || undefined}
  >
    {@render children?.()}
  </svelte:element>
{/if}

<style>
  .sky-card {
    display: block;
    box-sizing: border-box;
    min-width: 0;
    border: var(--ds-border-width) solid var(--ds-color-border);
    border-radius: var(--sky-radius-xl);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
    color: inherit;
    text-decoration: none;
    container-type: inline-size;
    transition:
      border-color var(--sky-duration-fast) var(--sky-ease-out),
      background-color var(--sky-duration-fast) var(--sky-ease-out);
  }
  .sky-card[data-padding='sm'] {
    padding: var(--ds-space-3) var(--ds-space-3-5);
  }
  .sky-card[data-padding='md'] {
    padding: var(--ds-space-4);
  }
  .sky-card[data-padding='lg'] {
    padding: var(--ds-space-5);
  }

  .sky-card[data-variant='header'] {
    border-radius: var(--sky-radius-2xl);
    background:
      radial-gradient(60% 130% at 100% 0%, var(--sky-color-hero-glow), transparent 70%),
      var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised-strong);
  }
  .sky-card[data-variant='raised'] {
    background: var(--ds-color-surface-raised);
    box-shadow: var(--sky-shadow-selected);
  }
  .sky-card[data-selected] {
    border-color: color-mix(in oklab, var(--ds-color-accent) 60%, var(--ds-color-border));
    background: var(--ds-color-surface-raised);
    box-shadow:
      var(--sky-shadow-selected),
      0 16px 40px -24px var(--ds-color-accent);
  }

  .sky-card[data-interactive] {
    cursor: pointer;
  }
  .sky-card[data-interactive]:hover {
    border-color: var(--sky-color-border-hover);
  }
  .sky-card:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }

  @media (min-width: 48rem) {
    .sky-card[data-padding='md'] {
      padding: var(--ds-space-5) var(--ds-space-6);
    }
    .sky-card[data-padding='lg'] {
      padding: var(--ds-space-8) var(--ds-space-9);
    }
  }
</style>
