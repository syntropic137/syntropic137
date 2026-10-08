<!--
  Rule Sentence (Triggers board, CompPatterns): a trigger read as a
  sentence, one clause per line: When, If, Then (with its input mapping),
  Cap and Log. Values sit in mono code chips; a failure value is coral.
-->
<script lang="ts">
  import { CLAUSE_LABEL, type RuleToken } from '@syn137/skyline-core/patterns'
  import type { RuleSentenceProps } from './types'

  let { clauses, size = 'compact', ...rest }: RuleSentenceProps = $props()
</script>

{#snippet token(t: RuleToken)}
  {#if typeof t === 'string'}{t}{:else if 'code' in t}<code class="sky-rule__code" data-tone={t.tone ?? 'neutral'}>{t.code}</code>{:else if 'muted' in t}<span class="sky-rule__muted">{t.muted}</span>{:else if t.href}<a class="sky-rule__link" href={t.href}>{t.link}</a>{:else}<span class="sky-rule__link">{t.link}</span>{/if}
{/snippet}

<div {...rest} class="sky-rule" data-size={size}>
  {#each clauses as c (c.key)}
    <div class="sky-rule__clause" data-key={c.key}>
      <span class="sky-rule__key" data-key={c.key}>{CLAUSE_LABEL[c.key]}</span>
      <div class="sky-rule__body">
        {#each c.lines as line, i (i)}
          <p class="sky-rule__line">{#each line as t, j (j)}{@render token(t)}{/each}</p>
        {/each}
        {#if c.mapping?.length}
          <div class="sky-rule__mapping-scroll">
            <dl class="sky-rule__mapping">
              {#each c.mapping as m (m.key)}
                <div class="sky-rule__map-row">
                  <dt>{m.key}</dt>
                  <span class="sky-rule__from-arrow" aria-hidden="true">←</span>
                  <dd>{m.from}</dd>
                </div>
              {/each}
            </dl>
          </div>
        {/if}
        {#if c.figures?.length}
          <dl class="sky-rule__figures">
            {#each c.figures as f (f.label)}
              <div><dt>{f.label}</dt><dd>{f.value}</dd></div>
            {/each}
          </dl>
        {/if}
        {#if c.detail}<span class="sky-rule__detail">{c.detail}</span>{/if}
      </div>
    </div>
  {/each}
</div>

<style>
  .sky-rule {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
    min-width: 0;
    font-size: var(--ds-text-md);
    line-height: 1.8;
  }
  .sky-rule__clause {
    display: grid;
    grid-template-columns: 2.75rem minmax(0, 1fr);
    gap: var(--ds-space-2) var(--ds-space-4);
    align-items: start;
  }
  .sky-rule[data-size='full'] {
    gap: 0;
    font-size: var(--sky-text-body);
  }
  .sky-rule[data-size='full'] .sky-rule__clause {
    padding: var(--ds-space-5) var(--ds-space-4);
    border-bottom: var(--ds-border-width) solid var(--ds-color-border);
  }
  .sky-rule[data-size='full'] .sky-rule__clause:last-child {
    border-bottom: 0;
  }
  @media (min-width: 48rem) {
    .sky-rule[data-size='full'] .sky-rule__clause {
      padding: var(--ds-space-5) var(--ds-space-6);
      gap: var(--ds-space-2) 1.125rem;
    }
  }
  .sky-rule__key {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2.75rem;
    height: 1.625rem;
    margin-top: 0.15em;
    border-radius: var(--ds-radius-sm);
    background: var(--sky-color-control-hover);
    font-family: var(--ds-font-mono);
    font-size: 0.625rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ds-color-text-muted);
  }
  .sky-rule__key[data-key='then'] {
    background: color-mix(in oklab, var(--ds-color-accent) 18%, transparent);
    color: var(--sky-color-accent-soft-fg);
  }
  .sky-rule__body {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1-5);
    min-width: 0;
  }
  .sky-rule__line {
    margin: 0;
    overflow-wrap: anywhere;
  }
  .sky-rule__code {
    padding: 2px var(--ds-space-2);
    border-radius: 7px;
    background: var(--sky-color-control-hover);
    font-family: var(--ds-font-mono);
    font-size: 0.75rem;
    overflow-wrap: anywhere;
  }
  .sky-rule__code[data-tone='danger'] {
    background: var(--sky-color-danger-soft);
    color: color-mix(in oklab, var(--ds-color-danger) 50%, var(--ds-color-fg));
  }
  .sky-rule__muted {
    color: var(--ds-color-text-subtle);
  }
  .sky-rule__link {
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
    text-decoration: underline;
    text-decoration-color: var(--sky-color-border-hover);
    text-underline-offset: 3px;
  }
  a.sky-rule__link:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
    border-radius: var(--ds-radius-xs);
  }
  .sky-rule__mapping-scroll {
    overflow-x: auto;
  }
  .sky-rule__mapping {
    display: flex;
    flex-direction: column;
    min-width: 22rem;
    margin: var(--ds-space-2) 0 0;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    line-height: 1.4;
  }
  .sky-rule__map-row {
    display: grid;
    grid-template-columns: minmax(8rem, 1fr) 1.25rem minmax(10rem, 1.6fr);
    column-gap: var(--ds-space-3);
    align-items: center;
    min-height: 2.25rem;
    border-bottom: var(--ds-border-width) solid var(--sky-color-divider);
  }
  .sky-rule__map-row dd {
    margin: 0;
    color: var(--ds-color-text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-rule__from-arrow {
    color: var(--ds-color-text-subtle);
  }
  .sky-rule__figures {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(7.5rem, 100%), 1fr));
    gap: var(--ds-space-4) var(--ds-space-6);
    margin: 0;
    line-height: 1.3;
  }
  .sky-rule__figures div {
    display: flex;
    flex-direction: column-reverse;
    gap: 2px;
  }
  .sky-rule__figures dd {
    margin: 0;
    font-size: var(--ds-text-2xl);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums;
  }
  .sky-rule__figures dt {
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
  .sky-rule__detail {
    font-size: var(--ds-text-sm);
    line-height: 1.5;
    color: var(--ds-color-text-muted);
  }
</style>
