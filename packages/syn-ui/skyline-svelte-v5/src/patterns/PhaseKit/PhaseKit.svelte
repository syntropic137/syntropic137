<!--
  Phase Kit (PhaseKit board): what a phase gets, as label and value rows:
  Model, Tools, Skills and, once pinned at run start, Used. Each absence
  reads as itself ("Harness default", "None declared", "Not recorded",
  "Not reported yet") in a dashed chip, never as an empty row.
-->
<script lang="ts">
  import { ABSENCE_TEXT, type KitAbsence } from '@syn137/skyline-core/patterns'
  import SkillRef from '../SkillRef/SkillRef.svelte'
  import type { PhaseKitProps } from './types'

  let { eyebrow, title, model, tools, toolsNote, skills, used, card = true, ...rest }: PhaseKitProps = $props()

  const isAbsence = (v: unknown): v is KitAbsence => typeof v === 'string'
</script>

<section {...rest} class="sky-kit" data-card={card || undefined} aria-label={rest['aria-label'] ?? title ?? 'Phase kit'}>
  {#if eyebrow || title}
    <div class="sky-kit__head">
      {#if eyebrow}<span class="sky-kit__eyebrow">{eyebrow}</span>{/if}
      {#if title}<span class="sky-kit__title">{title}</span>{/if}
    </div>
  {/if}
  <dl class="sky-kit__rows">
    <div class="sky-kit__row">
      <dt>Model</dt>
      <dd>
        {#if !model || model === 'not-recorded'}
          <span class="sky-kit__absent">{ABSENCE_TEXT['not-recorded']}</span>
        {:else}
          <span class="sky-kit__model">
            <span class="sky-kit__agent"><span class="sky-kit__dot" data-agent={model.agentKind ?? 'other'}></span>{model.agent}</span>
            {#if model.resolution}<span class="sky-kit__resolution">{model.resolution}</span>{/if}
          </span>
        {/if}
      </dd>
    </div>
    <div class="sky-kit__row">
      <dt>Tools</dt>
      <dd>
        {#if tools === 'default'}
          <span>{ABSENCE_TEXT.default}{#if toolsNote}&nbsp;<span class="sky-kit__muted">{toolsNote}</span>{/if}</span>
        {:else if isAbsence(tools)}
          <span class="sky-kit__absent">{ABSENCE_TEXT[tools]}</span>
        {:else if tools.length === 0}
          <span class="sky-kit__absent">No tools</span>
        {:else}
          <span class="sky-kit__tools">
            {#each tools as t (t)}<span class="sky-kit__tool">{t}</span>{/each}
          </span>
        {/if}
      </dd>
    </div>
    <div class="sky-kit__row">
      <dt>Skills</dt>
      <dd>
        {#if isAbsence(skills)}
          <span class="sky-kit__absent">{ABSENCE_TEXT[skills]}</span>
        {:else if skills.length === 0}
          <span class="sky-kit__absent">{ABSENCE_TEXT.none}</span>
        {:else}
          {#each skills as s (s.name)}<SkillRef {...s} />{/each}
        {/if}
      </dd>
    </div>
    {#if used !== undefined}
      <div class="sky-kit__row">
        <dt>Used</dt>
        <dd>
          {#if isAbsence(used)}
            <span class="sky-kit__absent">{ABSENCE_TEXT[used]}</span>
          {:else if used.length === 0}
            <span class="sky-kit__absent">None used</span>
          {:else}
            <span class="sky-kit__tools">{#each used as u (u)}<span class="sky-kit__tool">{u}</span>{/each}</span>
          {/if}
        </dd>
      </div>
    {/if}
  </dl>
</section>

<style>
  .sky-kit {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
  }
  .sky-kit[data-card] {
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-kit__head {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
  }
  .sky-kit__eyebrow,
  .sky-kit__row dt {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
  }
  .sky-kit__eyebrow {
    color: var(--sky-color-accent-soft-fg);
  }
  .sky-kit__title {
    font-size: var(--sky-text-body);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-kit__rows {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3-5);
    margin: 0;
  }
  .sky-kit__row {
    display: grid;
    grid-template-columns: 4rem minmax(0, 1fr);
    gap: var(--ds-space-3);
    padding-top: var(--ds-space-3-5);
    border-top: var(--ds-border-width) solid var(--ds-color-border);
  }
  .sky-kit__row dt {
    padding-top: 3px;
    color: var(--ds-color-text-subtle);
  }
  .sky-kit__row dd {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
    margin: 0;
    min-width: 0;
    font-size: 0.84375rem;
  }
  .sky-kit__model {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1-5) var(--ds-space-2);
  }
  .sky-kit__agent {
    display: flex;
    align-items: center;
    gap: var(--ds-space-1-5);
  }
  .sky-kit__dot {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: var(--ds-color-text-subtle);
  }
  .sky-kit__dot[data-agent='claude'] {
    background: var(--sky-color-agent-claude);
  }
  .sky-kit__dot[data-agent='codex'] {
    background: var(--sky-color-agent-codex);
  }
  .sky-kit__resolution {
    font-family: var(--ds-font-mono);
    font-size: 0.75rem;
    color: var(--ds-color-text-muted);
    overflow-wrap: anywhere;
  }
  .sky-kit__muted {
    color: var(--ds-color-text-muted);
  }
  .sky-kit__tools {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-1-5);
  }
  .sky-kit__tool {
    height: 1.375rem;
    padding: 0 var(--ds-space-2);
    border-radius: 7px;
    background: var(--sky-color-control-hover);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    line-height: 1.375rem;
    color: var(--sky-color-text-code);
  }
  .sky-kit__absent {
    align-self: flex-start;
    height: 1.5rem;
    padding: 0 var(--ds-space-2-5);
    border-radius: var(--ds-radius-sm);
    border: var(--ds-border-width) dashed var(--sky-color-border-hover);
    font-size: var(--sky-text-data);
    line-height: 1.375rem;
    color: var(--ds-color-text-muted);
  }
</style>
