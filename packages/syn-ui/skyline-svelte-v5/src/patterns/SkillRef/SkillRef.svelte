<!--
  Skill Ref (PhaseKit board): a skill's name, source and ref, a link to the
  source at that ref, and its content digest once pinned at run start. The
  `chip` variant is the compact form on workflow cards. The name links to the
  skill's SKILL.md at its pinned ref (skillSourceHref()); with no link the
  tooltip says why.
-->
<script lang="ts">
  import { GLYPH, skillRefDisplay } from '@syn137/skyline-core/patterns'
  import Glyph from '../Glyph/Glyph.svelte'
  import type { SkillRefProps } from './types'

  let { name, source, ref, href, digest, variant = 'full', ...rest }: SkillRefProps = $props()

  const s = $derived(skillRefDisplay({ name, source, ref, href, digest }))
</script>

{#if variant === 'chip'}
  <svelte:element
    this={s.href ? 'a' : 'span'}
    {...rest}
    class="sky-skill-chip"
    href={s.href ?? undefined}
    target={s.href ? '_blank' : undefined}
    rel={s.href ? 'noreferrer noopener' : undefined}
    title={s.title}
    aria-label={s.linkLabel ?? undefined}
  >
    <span class="sky-skill-chip__icon"><Glyph d={GLYPH.diamond} size={11} weight={1.75} /></span>
    <span>{s.name}</span>
    {#if s.ref}<span class="sky-skill-chip__ref">@{s.ref}</span>{/if}
  </svelte:element>
{:else}
  <span {...rest} class="sky-skill">
    <span class="sky-skill__tile"><Glyph d={GLYPH.diamond} size={13} weight={1.75} /></span>
    <span class="sky-skill__text">
      {#if s.href}
        <a class="sky-skill__name" href={s.href} title={s.title} target="_blank" rel="noreferrer noopener">{s.name}</a>
      {:else}
        <span class="sky-skill__name" title={s.title}>{s.name}</span>
      {/if}
      <span class="sky-skill__source">
        <span>{s.source}</span>
        {#if s.ref}<span class="sky-skill__at">@</span><span class="sky-skill__ref">{s.ref}</span>{/if}
        {#if s.href}
          <a class="sky-skill__link" href={s.href} aria-label={s.linkLabel} target="_blank" rel="noreferrer noopener"><Glyph d={GLYPH.external} size={13} weight={1.5} /></a>
        {/if}
      </span>
      {#if s.digest}
        <span class="sky-skill__digest"><span class="sky-skill__at">content</span><span>{s.digest}</span></span>
      {/if}
    </span>
  </span>
{/if}

<style>
  .sky-skill {
    display: flex;
    align-items: flex-start;
    gap: var(--ds-space-2-5);
    min-width: 0;
  }
  .sky-skill__tile {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 1.75rem;
    height: 1.75rem;
    border-radius: var(--ds-radius-sm);
    background: var(--sky-color-accent-soft);
    color: var(--ds-color-accent);
  }
  .sky-skill__text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .sky-skill__name {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
    overflow-wrap: anywhere;
  }
  a.sky-skill__name {
    color: var(--ds-color-fg);
    text-decoration: underline;
    text-decoration-color: var(--sky-color-border-hover);
    text-underline-offset: 3px;
  }
  a.sky-skill__name:hover {
    text-decoration-color: currentColor;
  }
  a.sky-skill__name:focus-visible,
  a.sky-skill-chip:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  a.sky-skill-chip {
    text-decoration: none;
  }
  a.sky-skill-chip:hover {
    border-color: var(--sky-color-border-hover);
  }
  .sky-skill-chip__ref {
    color: var(--ds-color-text-subtle);
  }
  .sky-skill__source,
  .sky-skill__digest {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 2px var(--ds-space-1-5);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
    overflow-wrap: anywhere;
  }
  .sky-skill__at {
    color: var(--ds-color-text-subtle);
  }
  .sky-skill__ref {
    color: var(--sky-color-text-code);
  }
  .sky-skill__link {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.375rem;
    height: 1.375rem;
    border-radius: 7px;
    color: var(--sky-color-accent-soft-fg);
  }
  .sky-skill__link:hover {
    background: var(--sky-color-control-hover);
  }
  .sky-skill__link:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-skill__link {
      width: var(--sky-size-touch);
      height: var(--sky-size-touch);
      margin: calc((var(--sky-size-touch) - 1.375rem) / -2) 0;
    }
  }
  .sky-skill-chip {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    height: 1.5rem;
    padding: 0 9px 0 7px;
    border-radius: var(--ds-radius-sm);
    border: var(--ds-border-width) solid var(--sky-color-border-muted);
    background: var(--sky-color-control-hover);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--sky-color-text-code);
    white-space: nowrap;
  }
  .sky-skill-chip__icon {
    display: inline-flex;
    color: var(--ds-color-accent);
  }
</style>
