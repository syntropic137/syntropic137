<script lang="ts">
  import { href, router } from '../lib/router'
  import type { PageProps } from '../lib/routes'

  let { params: _params }: PageProps = $props()
</script>

<section class="sky-notfound">
  <p class="sky-notfound__code">404</p>
  <h1>Nothing at {router.path}</h1>
  <p><a href={href('/')}>Back to Overview</a></p>
</section>

<style>
  .sky-notfound {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    padding: var(--ds-space-8) 0;
  }
  .sky-notfound__code {
    margin: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    color: var(--ds-color-text-subtle);
  }
  h1 {
    margin: 0;
    font-size: var(--sky-text-page);
    letter-spacing: var(--sky-tracking-display);
    overflow-wrap: anywhere;
  }
  p {
    margin: 0;
  }
</style>
