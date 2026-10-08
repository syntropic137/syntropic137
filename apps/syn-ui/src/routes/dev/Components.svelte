<!--
  /dev/components: every base component in skyline-svelte-v5 with its
  states, laid out like the CompActions, CompDisplay and CompNav boards.
  For review at phone and desktop widths; not in the nav.
-->
<script lang="ts">
  import { setPage } from '../../lib/page.svelte'
  import type { PageProps } from '../../lib/routes'
  import Actions from './parts/Actions.svelte'
  import Display from './parts/Display.svelte'
  import Navigation from './parts/Navigation.svelte'

  let { params: _params }: PageProps = $props()

  setPage({ title: 'Components', crumbs: [{ label: 'Components' }] })

  const boards = [
    { id: 'actions', label: 'Actions and inputs' },
    { id: 'display', label: 'Display' },
    { id: 'navigation', label: 'Navigation and overlays' },
  ]
</script>

<div class="gallery">
  <header class="gallery__head">
    <p class="gallery__eyebrow">Skyline · skyline-svelte-v5</p>
    <h1 class="gallery__title">Components</h1>
    <p class="gallery__lead">Base components with every state the screens use. Resize to 320px to check the phone layout.</p>
    <nav class="gallery__toc" aria-label="Boards">
      {#each boards as b (b.id)}<a href={`#${b.id}`}>{b.label}</a>{/each}
    </nav>
  </header>

  <section class="gallery__board" id="actions" aria-labelledby="actions-title">
    <h2 class="gallery__board-title" id="actions-title">Actions and inputs</h2>
    <div class="gallery__grid"><Actions /></div>
  </section>
  <section class="gallery__board" id="display" aria-labelledby="display-title">
    <h2 class="gallery__board-title" id="display-title">Display</h2>
    <div class="gallery__grid"><Display /></div>
  </section>
  <section class="gallery__board" id="navigation" aria-labelledby="navigation-title">
    <h2 class="gallery__board-title" id="navigation-title">Navigation and overlays</h2>
    <div class="gallery__grid"><Navigation /></div>
  </section>
</div>

<style>
  .gallery {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-10);
    padding-bottom: var(--ds-space-10);
  }
  .gallery__head {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
  }
  .gallery__eyebrow,
  .gallery__board-title {
    margin: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    font-weight: var(--ds-font-weight-regular);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .gallery__title {
    margin: 0;
    font-size: var(--sky-text-page);
    line-height: var(--ds-line-height-tight);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-display);
  }
  .gallery__lead {
    margin: 0;
    font-size: var(--sky-text-body);
    color: var(--ds-color-text-muted);
  }
  .gallery__toc {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-1) var(--ds-space-4);
    font-size: var(--ds-text-sm);
  }
  .gallery__toc a {
    display: inline-flex;
    align-items: center;
    min-height: var(--sky-size-touch);
    color: var(--ds-color-accent);
    text-decoration: none;
  }
  .gallery__toc a:hover {
    color: var(--ds-color-accent-hover);
  }
  .gallery__toc a:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .gallery__board {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    scroll-margin-top: var(--ds-space-4);
  }
  .gallery__grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--ds-space-5);
    align-items: start;
  }
  @media (min-width: 64rem) {
    .gallery__grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .gallery__toc a {
      min-height: 0;
    }
  }
</style>
