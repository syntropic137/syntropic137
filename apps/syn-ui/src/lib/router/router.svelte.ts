/**
 * A ~1 KB history router. No dependency, Svelte 5 runes for state.
 *
 * - Plain <a href="/executions"> links work: clicks on same-origin anchors
 *   are intercepted (unless modified, targeted or marked data-sky-reload).
 * - Hovering or focusing a link preloads that route's chunk.
 * - Paths are app paths ("/executions"); the deploy base (/next/) is added
 *   and stripped here, so pages never see it. Use href() to build links.
 */
import { notFoundRoute, routes, type RouteDef } from '../routes'
import { type CompiledPattern, type Params, compilePattern, matchPattern, stripBase, withBase } from './match'

const BASE = import.meta.env.BASE_URL ?? '/'

export interface Match {
  route: RouteDef
  params: Params
  /** Stable identity of this page instance: path + params. */
  key: string
}

const compiled: Array<{ route: RouteDef; pattern: CompiledPattern }> = routes.map((route) => ({ route, pattern: compilePattern(route.path) }))

export function resolve(path: string): Match {
  for (const { route, pattern } of compiled) {
    const params = matchPattern(pattern, path)
    if (params) return { route, params, key: `${route.path}|${JSON.stringify(params)}` }
  }
  return { route: notFoundRoute, params: {}, key: `*|${path}` }
}

/** App path -> URL with the deploy base. */
export function href(path: string): string {
  return withBase(path, BASE)
}

class Router {
  /** App path without base, e.g. "/executions/abc". */
  path = $state(typeof location === 'undefined' ? '/' : stripBase(location.pathname, BASE))
  /** Query string including "?", or "". */
  search = $state(typeof location === 'undefined' ? '' : location.search)
  match: Match = $derived(resolve(this.path))
  /** URLSearchParams view of `search` (read-only; use setQuery to change). */
  query: URLSearchParams = $derived(new URLSearchParams(this.search))

  private started = false

  navigate(to: string, options: { replace?: boolean; scroll?: boolean } = {}): void {
    const url = new URL(to, location.origin + withBase(this.path, BASE))
    const path = stripBase(url.pathname, BASE)
    const target = withBase(path, BASE) + url.search + url.hash
    if (options.replace) history.replaceState(history.state, '', target)
    else history.pushState(null, '', target)
    this.path = path
    this.search = url.search
    if (options.scroll !== false && !options.replace) window.scrollTo({ top: 0 })
  }

  /** Merge query params into the URL (replace by default: filters should not flood history). */
  setQuery(changes: Record<string, string | null | undefined>, options: { push?: boolean } = {}): void {
    const q = new URLSearchParams(this.search)
    for (const [k, v] of Object.entries(changes)) {
      if (v === null || v === undefined || v === '') q.delete(k)
      else q.set(k, v)
    }
    const qs = q.toString()
    this.navigate(`${withBase(this.path, BASE)}${qs ? `?${qs}` : ''}`, { replace: !options.push, scroll: false })
  }

  /** Warm the chunk for a path (hover/focus prefetch). */
  preload(path: string): void {
    void resolve(path).route.load?.()
  }

  start(): () => void {
    if (this.started) return () => {}
    this.started = true
    const onPop = () => {
      this.path = stripBase(location.pathname, BASE)
      this.search = location.search
    }
    const linkFrom = (e: Event): HTMLAnchorElement | null => {
      const a = (e.target as Element | null)?.closest?.('a')
      if (!a || !a.href || a.target || a.hasAttribute('download') || a.dataset.skyReload !== undefined) return null
      const url = new URL(a.href)
      if (url.origin !== location.origin) return null
      const base = BASE.endsWith('/') ? BASE : BASE + '/'
      if (!(url.pathname + '/').startsWith(base)) return null
      return a
    }
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
      const a = linkFrom(e)
      if (!a) return
      const url = new URL(a.href)
      // Same-page hash links keep native behaviour.
      if (url.pathname === location.pathname && url.search === location.search && url.hash) return
      e.preventDefault()
      this.navigate(url.pathname + url.search + url.hash)
    }
    const onIntent = (e: Event) => {
      const a = linkFrom(e)
      if (a) this.preload(stripBase(new URL(a.href).pathname, BASE))
    }
    addEventListener('popstate', onPop)
    document.addEventListener('click', onClick)
    document.addEventListener('pointerover', onIntent, { passive: true })
    document.addEventListener('focusin', onIntent)
    return () => {
      removeEventListener('popstate', onPop)
      document.removeEventListener('click', onClick)
      document.removeEventListener('pointerover', onIntent)
      document.removeEventListener('focusin', onIntent)
      this.started = false
    }
  }
}

export const router = new Router()
