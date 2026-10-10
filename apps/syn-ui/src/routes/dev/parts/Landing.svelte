<!--
  /dev/patterns, Landing boards (Landing, PhoneLanding v4): the shared
  product visuals the landing page uses as <sky-*> elements. Sample data
  comes from each pattern's examples.ts. Motion is the opt-in motion.css,
  as on the landing; every animation is finite and ends in the static state.
-->
<script lang="ts">
  import '@syn137/skyline-themes/motion.css'
  import { EvalExplorer, HarnessChip, HarnessLanes, HeroCity, SMark, ToolLogTicker, UsageBand } from '@syn137/skyline-svelte-v5/patterns'
  import {
    EVAL_EXPLORER_EXAMPLE,
    HARNESS_CHIP_EXAMPLES,
    HARNESS_LANES_EXAMPLES,
    HERO_CITY_EXAMPLES,
    S_MARK_EXAMPLES,
    TOOL_LOG_EXAMPLE_ROWS,
    USAGE_BAND_EXAMPLES,
  } from '@syn137/skyline-svelte-v5/examples'

  const [heroDesktop, heroPhone] = HERO_CITY_EXAMPLES
  const [lanes, lanesShort] = HARNESS_LANES_EXAMPLES
  const [meterBand, landingBand, emptyBand] = USAGE_BAND_EXAMPLES
  let pick = $state<number | undefined>(undefined)
</script>

<section class="dev-landing" aria-labelledby="p-landing">
  <h2 id="p-landing">Landing: S Mark and Hero City</h2>
  <p class="dev-landing__note">Hero: the run city with the S rising from the middle. Blocks rise, live days pulse and failed days flash a few times, then everything stops.</p>
  {#if heroDesktop}
    <div class="dev-landing__hero">
      <HeroCity {...heroDesktop.props}>
        {#snippet overlay()}<div class="dev-landing__s"><SMark animate label="The Syntropic137 S, built from cubes" /></div>{/snippet}
      </HeroCity>
    </div>
  {/if}
  <div class="dev-landing__row">
    {#each S_MARK_EXAMPLES as e (e.name)}
      <figure class="dev-landing__figure"><SMark {...e.props} /><figcaption>{e.name}</figcaption></figure>
    {/each}
    {#if heroPhone}
      <figure class="dev-landing__figure dev-landing__phone"><HeroCity {...heroPhone.props} /><figcaption>{heroPhone.name}</figcaption></figure>
    {/if}
  </div>
</section>

<section class="dev-landing" aria-labelledby="p-harness">
  <h2 id="p-harness">Landing: Harness Chip and Harness Lanes</h2>
  <div class="dev-landing__row-tight">
    {#each HARNESS_CHIP_EXAMPLES as c, i (i)}<HarnessChip {...c} />{/each}
  </div>
  <div class="dev-landing__panels">
    {#if lanes}
      <div class="dev-landing__panel">
        <span class="dev-landing__eyebrow">plan-implement-review · one workflow, two vendors</span>
        <HarnessLanes {...lanes} />
      </div>
    {/if}
    {#if lanesShort}
      <div class="dev-landing__panel dev-landing__narrow">
        <span class="dev-landing__eyebrow">implement-and-review</span>
        <HarnessLanes {...lanesShort} />
      </div>
    {/if}
  </div>
</section>

<section class="dev-landing" aria-labelledby="p-observe">
  <h2 id="p-observe">Landing: Usage Band and Tool Log Ticker</h2>
  <div class="dev-landing__panels">
    {#if landingBand}
      <div class="dev-landing__panel">
        <span class="dev-landing__eyebrow">live · implement-and-review · run #142</span>
        <span class="dev-landing__figures"><span class="dev-landing__cost">$0.2162</span><span class="dev-landing__mono">1.12M tokens · 214 tool calls · 6m 12s</span></span>
        <UsageBand {...landingBand.props} />
        <ToolLogTicker rows={TOOL_LOG_EXAMPLE_ROWS} />
      </div>
    {/if}
    <div class="dev-landing__panel dev-landing__narrow">
      {#if meterBand}<span class="dev-landing__eyebrow">{meterBand.name}</span><UsageBand {...meterBand.props} />{/if}
      {#if emptyBand}<span class="dev-landing__eyebrow">{emptyBand.name}</span><UsageBand {...emptyBand.props} />{/if}
      <span class="dev-landing__eyebrow">Ticker, still (speed 0)</span>
      <ToolLogTicker rows={TOOL_LOG_EXAMPLE_ROWS.slice(0, 4)} speed={0} />
    </div>
  </div>
</section>

<section class="dev-landing" aria-labelledby="p-explorer">
  <h2 id="p-explorer">Landing: Eval Explorer</h2>
  <p class="dev-landing__note">Arrow keys, Home and End move the pick in rank order; pointing with a mouse picks too. Picked: <code>{pick ?? 'best'}</code>.</p>
  <div class="dev-landing__frame">
    <div class="dev-landing__window">
      <div class="dev-landing__chrome"><span class="dev-landing__dots" aria-hidden="true"><span></span><span></span><span></span></span><span class="dev-landing__mono">localhost:8137/evals/shared-esp-stream</span></div>
      <EvalExplorer {...EVAL_EXPLORER_EXAMPLE} bind:selected={pick} />
    </div>
  </div>
</section>

<style>
  .dev-landing {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
  }
  .dev-landing > h2 {
    margin: 0;
    font-size: var(--ds-text-xl);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
  }
  .dev-landing__note {
    margin: 0;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .dev-landing__hero {
    overflow: hidden;
    padding: var(--ds-space-6) 0 0;
    border-radius: var(--sky-radius-2xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--sky-glow-accent-wash), var(--sky-texture-dots), var(--sky-color-ground-deep);
  }
  .dev-landing__s {
    width: 15%;
    margin-top: 2%;
  }
  .dev-landing__row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--ds-space-5) var(--ds-space-8);
  }
  .dev-landing__row-tight {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2);
  }
  .dev-landing__figure {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--ds-space-2-5);
    margin: 0;
  }
  .dev-landing__figure figcaption,
  .dev-landing__mono {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .dev-landing__phone {
    width: min(100%, 22rem);
  }
  .dev-landing__panels {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--ds-space-5);
  }
  @media (min-width: 64rem) {
    .dev-landing__panels {
      grid-template-columns: minmax(0, 1fr) var(--sky-side-column);
    }
  }
  .dev-landing__panel {
    display: flex;
    flex-direction: column;
    gap: 14px;
    min-width: 0;
    padding: 1.125rem;
    border-radius: var(--sky-radius-card-lg);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--sky-gradient-panel);
    box-shadow: var(--sky-shadow-raised-strong);
  }
  @media (min-width: 48rem) {
    .dev-landing__panel {
      padding: var(--ds-space-7);
    }
    .dev-landing__narrow {
      padding: 1.125rem;
    }
  }
  .dev-landing__eyebrow {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .dev-landing__figures {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 6px 20px;
  }
  .dev-landing__cost {
    font-size: var(--sky-text-figure);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.03em;
  }
  .dev-landing__frame {
    padding: 1px;
    border-radius: 26px;
    background: var(--sky-border-gradient);
    box-shadow: var(--sky-glow-accent-strong);
  }
  .dev-landing__window {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    padding: 0 var(--ds-space-4) var(--ds-space-4);
    border-radius: 25px;
    background: var(--sky-gradient-window);
  }
  @media (min-width: 48rem) {
    .dev-landing__window {
      padding: 0 var(--ds-space-7) var(--ds-space-7);
    }
  }
  .dev-landing__chrome {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 0 calc(-1 * var(--ds-space-4));
    padding: 12px 16px;
    border-bottom: var(--ds-border-width) solid var(--sky-color-divider);
    min-width: 0;
  }
  @media (min-width: 48rem) {
    .dev-landing__chrome {
      margin: 0 calc(-1 * var(--ds-space-7));
    }
  }
  .dev-landing__dots {
    display: flex;
    gap: 6px;
  }
  .dev-landing__dots span {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--sky-color-border-strong);
  }
</style>
