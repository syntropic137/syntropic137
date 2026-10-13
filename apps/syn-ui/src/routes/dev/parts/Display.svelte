<!-- /dev/components, board CompDisplay: badges, tags, stats, cards, callouts, meters and empty states. -->
<script lang="ts">
  import {
    Accordion,
    Badge,
    Button,
    Callout,
    Card,
    Collapsible,
    EmptyState,
    Meter,
    Progress,
    ScrollArea,
    Separator,
    Skeleton,
    Stat,
    Tag,
  } from '@syn137/skyline-svelte-v5'
  import { StatusBadge } from '@syn137/skyline-svelte-v5/patterns'

  const statuses = ['completed', 'failed', 'cancelled', 'running', 'pending']
  const lines = Array.from({ length: 14 }, (_, i) => `{"type":"assistant","seq":${i + 1},"message":"…"}`)
</script>

<section class="demo" aria-labelledby="demo-badge">
  <header>
    <h3 id="demo-badge">Badge</h3>
    <p class="demo__contract">BadgeContract · required</p>
    <p>Status pairs a glyph with the word, so it reads without colour.</p>
  </header>
  <div class="demo__row">
    {#each statuses as s (s)}<figure><StatusBadge status={s} /><figcaption>{s}</figcaption></figure>{/each}
  </div>
  <div class="demo__row">
    <figure><Badge variant="soft" tone="accent" dot>Pass</Badge><figcaption>verdict · pass</figcaption></figure>
    <figure><Badge variant="soft" tone="danger" dot>Fail</Badge><figcaption>verdict · fail</figcaption></figure>
    <figure><Badge variant="soft" tone="warning" dot>Error</Badge><figcaption>verdict · error</figcaption></figure>
    <figure><Badge variant="outline" tone="neutral">Unscored</Badge><figcaption>verdict · unscored</figcaption></figure>
    <figure><Badge variant="solid" tone="accent" size="sm">New</Badge><figcaption>solid · sm</figcaption></figure>
  </div>
</section>

<section class="demo" aria-labelledby="demo-tag">
  <header>
    <h3 id="demo-tag">Tag and chips</h3>
    <p class="demo__contract">pattern · Badge</p>
    <p>Accent tags filter when clicked; neutral chips only label.</p>
  </header>
  <div class="demo__row">
    <figure><Tag variant="accent" onclick={() => {}}>case:shared-esp-stream</Tag><figcaption>tag, clickable</figcaption></figure>
    <figure><Tag variant="outline">research</Tag><figcaption>type</figcaption></figure>
    <figure><Tag variant="skill">vendored-scribe</Tag><figcaption>skill</figcaption></figure>
    <figure><Tag variant="agent" agent="claude">Claude · haiku requested</Tag><figcaption>agent</figcaption></figure>
    <figure><Tag variant="agent" agent="codex">Codex · gpt-6.1</Tag><figcaption>agent · codex</figcaption></figure>
    <figure><Tag variant="dashed">no skills</Tag><figcaption>missing value</figcaption></figure>
  </div>
</section>

<section class="demo" aria-labelledby="demo-stat">
  <header>
    <h3 id="demo-stat">Stat</h3>
    <p class="demo__contract">pattern</p>
    <p>Caps label above a tabular figure. 30px on desktop headers, 26px on phone.</p>
  </header>
  <div class="demo__row">
    <figure><Stat label="Sessions" value="108" size="hero" /><figcaption>header</figcaption></figure>
    <figure><Stat label="Spend" value="$6.92" size="md" /><figcaption>desktop</figcaption></figure>
    <figure><Stat label="Runs" value={12} size="sm" /><figcaption>phone</figcaption></figure>
    <figure><Stat label="Pass rate" value={null} /><figcaption>unknown</figcaption></figure>
  </div>
</section>

<section class="demo" aria-labelledby="demo-card">
  <header>
    <h3 id="demo-card">Card</h3>
    <p class="demo__contract">pattern</p>
    <p>Three levels: the header card with a glow, the standard card, the selected or raised card.</p>
  </header>
  <div class="demo__cards">
    <figure><Card variant="header" padding="md"><span class="demo__card-text">Research Workflow</span></Card><figcaption>header</figcaption></figure>
    <figure><Card padding="md"><span class="demo__card-text">Standard</span></Card><figcaption>standard</figcaption></figure>
    <figure><Card variant="raised" padding="md" selected><span class="demo__card-text">Selected</span></Card><figcaption>selected</figcaption></figure>
    <figure><Card padding="md" interactive href="#display"><span class="demo__card-text">Interactive link</span></Card><figcaption>interactive</figcaption></figure>
  </div>
</section>

<section class="demo" aria-labelledby="demo-callout">
  <header>
    <h3 id="demo-callout">Callout</h3>
    <p class="demo__contract">pattern</p>
    <p>Amber says something is uncertain, coral says something failed.</p>
  </header>
  <div class="demo__stack">
    <Callout tone="warning" title="Coverage can't be proven.">Others may exist.</Callout>
    <Callout tone="danger" title="Phase failed.">
      The verify report was not written.
      {#snippet action()}<Button variant="outline" size="sm">Retry</Button>{/snippet}
    </Callout>
    <Callout tone="note" title="Not scored yet.">A verdict appears once judged.</Callout>
  </div>
</section>

<section class="demo" aria-labelledby="demo-meter">
  <header>
    <h3 id="demo-meter">Meter, Progress, Skeleton, Separator</h3>
    <p class="demo__contract">MeterContract · ProgressContract · SeparatorContract</p>
    <p>Meters compare amounts; progress shows a running execution.</p>
  </header>
  <div class="demo__stack">
    <figure class="demo__wide"><Meter label="Codex delegates to Claude" valueText="26 runs" value={26} max={40} series="claude" /><figcaption>meter</figcaption></figure>
    <figure class="demo__wide"><Meter label="Cache read" valueText="90.9%" value={90.9} max={100} series="data-1" /><figcaption>meter · data series</figcaption></figure>
    <figure class="demo__wide"><Progress value={2} max={3} segments={3} valueText="phase 2 of 3" aria-label="Phases" /><figcaption>progress · phase 2 of 3</figcaption></figure>
    <figure class="demo__wide"><Progress value={null} aria-label="Starting" /><figcaption>progress · indeterminate</figcaption></figure>
    <figure class="demo__wide"><Skeleton variant="title" width="12ch" /><Skeleton variant="text" lines={2} /><figcaption>skeleton</figcaption></figure>
    <figure class="demo__wide"><Separator /><figcaption>separator</figcaption></figure>
  </div>
</section>

<section class="demo" aria-labelledby="demo-disclosure">
  <header>
    <h3 id="demo-disclosure">Accordion, Collapsible, Scroll Area</h3>
    <p class="demo__contract">AccordionContract · CollapsibleRootContract · ScrollAreaContract</p>
    <p>Sections open in place; long output scrolls inside its own box.</p>
  </header>
  <div class="demo__stack">
    <Accordion
      type="single"
      defaultValue={['summary']}
      items={[
        { value: 'summary', title: 'Executive Summary', meta: '2 min' },
        { value: 'scope', title: 'Research Scope & Methodology' },
        { value: 'locked', title: 'Appendix', disabled: true },
      ]}
    >
      {#snippet children(item)}<p>Contents of {item.title}.</p>{/snippet}
    </Accordion>
    <Collapsible title="Outline" meta="2 sections" defaultOpen>
      <p>Executive Summary · Research Scope &amp; Methodology</p>
    </Collapsible>
    <ScrollArea maxHeight="8rem" aria-label="Transcript sample">
      <pre class="demo__pre">{lines.join('\n')}</pre>
    </ScrollArea>
  </div>
</section>

<section class="demo" aria-labelledby="demo-empty">
  <header>
    <h3 id="demo-empty">Empty State</h3>
    <p class="demo__contract">pattern</p>
    <p>Says why the list is empty and what to do next.</p>
  </header>
  <EmptyState title="No evals tagged case:codex-cost-limit" description="Launch the suite with scripts/eval_suite.py, or clear the filter." level={4}>
    {#snippet action()}<Button variant="outline" size="sm">Clear filter</Button>{/snippet}
  </EmptyState>
</section>

<style>
  .demo {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
  }
  .demo header {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
  }
  .demo h3 {
    margin: 0;
    font-size: var(--ds-text-lg);
    font-weight: var(--ds-font-weight-semibold);
  }
  .demo p {
    margin: 0;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .demo .demo__contract {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .demo__row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--ds-space-4) var(--ds-space-5);
  }
  figure {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--ds-space-2);
    margin: 0;
    min-width: 0;
  }
  .demo__wide {
    flex: 1 1 100%;
    align-items: stretch;
  }
  figcaption {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }

  .demo__stack {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
  }
  .demo__cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr));
    gap: var(--ds-space-4);
  }
  .demo__cards figure {
    align-items: stretch;
  }
  .demo__card-text {
    font-size: var(--ds-text-sm);
  }
  .demo__pre {
    margin: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--sky-color-text-code);
    white-space: pre;
  }
</style>
