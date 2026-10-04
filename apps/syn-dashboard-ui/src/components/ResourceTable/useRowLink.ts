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
 * Events that start on a control INSIDE the row (its selection checkbox, an
 * action button, a nested link) belong to that control, never to the row: they
 * still bubble here, so each handler ignores them rather than relying on every
 * control to stop propagation for every event type.
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

/** Elements that own their clicks and keys; the row must not act on them. */
const INTERACTIVE = [
  'a[href]',
  'button',
  'input',
  'select',
  'textarea',
  'label',
  'summary',
  '[contenteditable=""]',
  '[contenteditable="true"]',
  '[role="button"]',
  '[role="checkbox"]',
  '[role="link"]',
  '[role="menuitem"]',
  '[role="switch"]',
  '[role="tab"]',
].join(',')

/** True when the event started on an interactive element nested in the row. */
function fromNestedControl(e: React.SyntheticEvent): boolean {
  const target = e.target
  if (!(target instanceof Element)) return false
  const control = target.closest(INTERACTIVE)
  return control !== null && control !== e.currentTarget && e.currentTarget.contains(control)
}

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
    onClick: (e) => {
      if (fromNestedControl(e)) return
      go(e.metaKey || e.ctrlKey)
    },
    onAuxClick: (e) => {
      if (e.button !== MIDDLE_BUTTON || fromNestedControl(e)) return
      go(true)
    },
    onKeyDown: (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return
      if (fromNestedControl(e)) return
      e.preventDefault()
      go(e.metaKey || e.ctrlKey)
    },
  }
}
