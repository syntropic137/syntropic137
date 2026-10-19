<script lang="ts">
  import { onMount, type Component } from 'svelte'
  import { live } from './lib/live.svelte'
  import { page, setPage } from './lib/page.svelte'
  import { type PageProps } from './lib/routes'
  import { router, type Match } from './lib/router'
  import AppShell from './shell/AppShell.svelte'
  import RouteError from './shell/RouteError.svelte'
  import { COMMAND_EVENT, overlays, requestPalette } from './shell/overlays.svelte'

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

  onMount(() => {
    const stopRouter = router.start()
    const stopLive = live.start()
    // One keymap (skyline-core KEYMAP) for every shortcut, ⌘K included. Loaded
    // right after start, beside the first route chunk, so it stays out of the first load.
    let stopKeys = () => {}
    let stopped = false
    void import('./shell/keyboard').then((m) => {
      if (!stopped) stopKeys = m.startKeyboard()
    })
    // Every palette entry point (⌘K, the search buttons, the desktop shortcut) fires this event.
    const openPalette = () => overlays.openPalette()
    addEventListener(COMMAND_EVENT, openPalette)
    return () => {
      stopRouter()
      stopLive()
      stopped = true
      stopKeys()
      removeEventListener(COMMAND_EVENT, openPalette)
    }
  })

  const area = $derived(shown?.match.route.area ?? router.match.route.area)
</script>

<AppShell active={area} crumbs={page.crumbs} live={live.state} onsearch={requestPalette}>
  {#if loadError}
    <RouteError error={loadError} />
  {:else if shown}
    {#key shown.match.key}
      <shown.Page params={shown.match.params} />
    {/key}
  {/if}
</AppShell>
