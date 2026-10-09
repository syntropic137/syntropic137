<!--
  Page Header (Execution, Workflow, Evals and phone boards): the section's
  3D Object Icon, a mono eyebrow, the status, the title and one line of
  context, with figures and actions. Stacks on a phone (icon 48px, figures
  in two columns); from a 44rem container the figures move to the right
  and the icon grows to 84px.
-->
<script lang="ts">
  import ObjectIcon from '../ObjectIcon/ObjectIcon.svelte'
  import StatusBadge from '../StatusBadge/StatusBadge.svelte'
  import type { PageHeaderProps } from './types'

  let {
    kind,
    title,
    eyebrow,
    titleLabel,
    description,
    status,
    meta,
    figures = [],
    figureColumns = 2,
    actions,
    children,
    titleAction,
    level = 1,
    ...rest
  }: PageHeaderProps = $props()
</script>

<section {...rest} class="sky-page-header" aria-label={rest['aria-label'] ?? title}>
  <div class="sky-page-header__inner">
    <div class="sky-page-header__main">
      <span class="sky-page-header__icon"><ObjectIcon {kind} size={84} /></span>
      <div class="sky-page-header__text">
        {#if eyebrow}<span class="sky-page-header__eyebrow">{eyebrow}</span>{/if}
        {#if status || meta}
          <div class="sky-page-header__meta">
            {#if status}<StatusBadge {status} />{/if}
            {#if meta}<span>{meta}</span>{/if}
          </div>
        {/if}
        <div class="sky-page-header__titles">
          {#if titleLabel}
            <span class="sky-page-header__label">{titleLabel}{#if titleAction}{@render titleAction()}{/if}</span>
          {/if}
          <svelte:element this={level === 1 ? 'h1' : 'h2'} class="sky-page-header__title">{title}</svelte:element>
          {#if description}<p class="sky-page-header__description">{description}</p>{/if}
        </div>
        {#if children}<div class="sky-page-header__extra">{@render children()}</div>{/if}
      </div>
    </div>
    {#if actions || figures.length}
      <div class="sky-page-header__side">
        {#if actions}<div class="sky-page-header__actions">{@render actions()}</div>{/if}
        {#if figures.length}
          <dl class="sky-page-header__figures" data-columns={figureColumns}>
            {#each figures as f (f.label)}
              <div class="sky-page-header__figure">
                <dt class="sky-page-header__figure-label">{f.label}</dt>
                <dd class="sky-page-header__figure-value">{f.value}</dd>
              </div>
            {/each}
          </dl>
        {/if}
      </div>
    {/if}
  </div>
</section>

<style>
  .sky-page-header {
    container-type: inline-size;
    border-radius: var(--sky-radius-2xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background:
      radial-gradient(70% 70% at 100% 0%, var(--sky-color-hero-glow), transparent 70%),
      var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised-strong);
  }
  .sky-page-header__inner {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    padding: var(--ds-space-5);
  }
  .sky-page-header__main {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: var(--ds-space-4);
    min-width: 0;
  }
  .sky-page-header__icon {
    display: block;
    flex-shrink: 0;
    width: var(--sky-size-object-icon-sm);
    height: var(--sky-size-object-icon-sm);
  }
  .sky-page-header__icon :global(svg) {
    width: 100%;
    height: 100%;
  }
  .sky-page-header__text {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-page-header__eyebrow {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-subtle);
    overflow-wrap: anywhere;
  }
  .sky-page-header__meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2-5);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-page-header__titles {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1-5);
    min-width: 0;
  }
  .sky-page-header__label {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-page-header__title {
    margin: 0;
    font-size: var(--sky-text-page);
    line-height: var(--ds-line-height-tight);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-display);
    text-wrap: balance;
    overflow-wrap: anywhere;
  }
  .sky-page-header__description {
    margin: 0;
    max-width: 48rem;
    font-size: var(--sky-text-body);
    color: var(--ds-color-text-muted);
    text-wrap: pretty;
  }
  .sky-page-header__extra > :global(*) {
    max-width: 100%;
  }
  .sky-page-header__extra {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2-5) var(--ds-space-3-5);
    min-width: 0;
  }
  .sky-page-header__side {
    display: flex;
    flex-direction: column-reverse;
    gap: var(--ds-space-5);
  }
  .sky-page-header__actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-2-5);
  }
  .sky-page-header__figures {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--ds-space-4) var(--ds-space-5);
    margin: 0;
  }
  .sky-page-header__figure {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    min-width: 0;
  }
  .sky-page-header__figure-label {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-page-header__figure-value {
    margin: 0;
    font-size: var(--sky-text-figure);
    line-height: 1.1;
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
    overflow-wrap: anywhere;
  }

  @container (min-width: 44rem) {
    .sky-page-header__inner {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--ds-space-7) var(--ds-space-14);
      padding: var(--ds-space-8) var(--ds-space-9);
    }
    .sky-page-header__main {
      flex-direction: row;
      align-items: flex-start;
      gap: var(--ds-space-6);
      flex: 1 1 28rem;
      max-width: 50rem;
    }
    .sky-page-header__icon {
      width: var(--sky-size-object-icon-lg);
      height: var(--sky-size-object-icon-lg);
    }
    .sky-page-header__side {
      flex-direction: column;
      align-items: flex-end;
      gap: var(--ds-space-6);
    }
    .sky-page-header__figures {
      grid-template-columns: repeat(2, minmax(6.5rem, auto));
      gap: var(--ds-space-5) var(--ds-space-10);
    }
    .sky-page-header__figures[data-columns='3'] {
      grid-template-columns: repeat(3, minmax(6rem, auto));
    }
  }
</style>
