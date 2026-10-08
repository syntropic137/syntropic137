<script lang="ts">
  import { onMount, type Component } from 'svelte'
  import { live } from './lib/live.svelte'
  import { page, setPage } from './lib/page.svelte'
  import { type PageProps } from './lib/routes'
  import { router, type Match } from './lib/router'
  import AppShell from './shell/AppShell.svelte'
  import RouteError from './shell/RouteError.svelte'

  /** The page on screen; swapped only once the next page's chunk has loaded. */
  let shown = $state<{ match: Match; Page: Component<PageProps> } | null>(null)
  let loadError = $state<unknown>(null)

  $effect(() => {
    const match = router.match
    if (match.route.redirect) {
      router.navigate(match.route.redirect, { replace: true })
      return
    }
    let cancelled = false
    loadError = null
    match.route.load?.().then(
      (mod) => {
        if (cancelled) return
        setPage({ title: match.route.title(match.params), crumbs: match.route.crumbs(match.params) })
        shown = { match, Page: mod.default }
      },
      (e: unknown) => {
        if (!cancelled) loadError = e
      },
    )
    return () => {
      cancelled = true
    }
  })

  $effect(() => {
    document.title = page.title ? `${page.title} · Syntropic137` : 'Syntropic137'
  })

  function openCommand() {
    // TODO(#624): the Command palette (Overlays wave) listens for this event.
    window.dispatchEvent(new CustomEvent('sky:command'))
  }

  onMount(() => {
    const stopRouter = router.start()
    const stopLive = live.start()
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        openCommand()
      }
    }
    addEventListener('keydown', onKey)
    return () => {
      stopRouter()
      stopLive()
      removeEventListener('keydown', onKey)
    }
  })

  const area = $derived(shown?.match.route.area ?? router.match.route.area)
</script>

<AppShell active={area} crumbs={page.crumbs} live={live.state} onsearch={openCommand}>
  {#if loadError}
    <RouteError error={loadError} />
  {:else if shown}
    {#key shown.match.key}
      <shown.Page params={shown.match.params} />
    {/key}
  {/if}
</AppShell>
