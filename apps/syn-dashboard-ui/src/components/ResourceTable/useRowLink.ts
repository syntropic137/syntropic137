/**
 * Make a table row or card behave like a link to `href`.
 *
 * A `<tr>` cannot be wrapped in an `<a>`, so a row that navigated through an
 * `onClick` lost everything a browser gives a link for free: cmd/ctrl-click
 * and middle-click just changed the page. This restores that behaviour in one
 * place so every list using ResourceTable or ResourceCardList gets it:
 *
 *   - plain click / Enter / Space  -> in-app navigation
 *   - cmd/ctrl-click, cmd/ctrl-Enter, middle-click -> a new tab
 *
 * Callers say WHERE a row goes, never HOW it gets there.
 */

import { useNavigate } from 'react-router-dom'

export interface RowLinkProps {
  role: 'link'
  tabIndex: 0
  onClick: (e: React.MouseEvent) => void
  onAuxClick: (e: React.MouseEvent) => void
  onKeyDown: (e: React.KeyboardEvent) => void
}

const MIDDLE_BUTTON = 1

export function useRowLink(href: string | undefined): RowLinkProps | undefined {
  const navigate = useNavigate()
  if (href === undefined) return undefined

  const go = (newTab: boolean) => {
    if (newTab) window.open(href, '_blank', 'noopener')
    else navigate(href)
  }
  return {
    role: 'link',
    tabIndex: 0,
    onClick: (e) => go(e.metaKey || e.ctrlKey),
    onAuxClick: (e) => {
      if (e.button === MIDDLE_BUTTON) go(true)
    },
    onKeyDown: (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return
      e.preventDefault()
      go(e.metaKey || e.ctrlKey)
    },
  }
}
