import type { Snippet } from 'svelte'
import type { DropdownMenuRootContract } from '@syn137/skyline-core/contracts'
import type { TriggerProps } from '../_internal/trigger'

export interface MenuItem {
  type?: 'item'
  label: string
  /** Stable key; defaults to the label. */
  value?: string
  /** Mono figure on the right ("65"). */
  meta?: string
  /** Renders a link (navigation menus such as More on the dock). */
  href?: string
  /** Marks the current page among link items. */
  current?: boolean
  disabled?: boolean
  tone?: 'neutral' | 'danger'
  icon?: Snippet
  onSelect?: () => void
}
export interface MenuSeparator {
  type: 'separator'
}
export interface MenuLabel {
  type: 'label'
  label: string
}
export type MenuEntry = MenuItem | MenuSeparator | MenuLabel

/**
 * Dropdown Menu (DropdownMenuRootContract). CompNav "dropdown · More on the
 * dock": rows with a label and a mono figure. Row actions and More.
 *
 * Keyboard: Enter, Space or ArrowDown on the trigger opens on the first item,
 * ArrowUp on the last; arrows, Home, End and type-ahead move; Enter selects;
 * Escape closes and returns focus; Tab closes.
 */
export interface DropdownMenuProps extends DropdownMenuRootContract {
  items: MenuEntry[]
  /** Accessible name of the menu (defaults to the trigger's name). */
  label?: string
  side?: 'top' | 'right' | 'bottom' | 'left'
  align?: 'start' | 'center' | 'end'
  /** CSS width, default 13.75rem (220px). */
  width?: string
  onSelect?: (item: MenuItem) => void
  trigger: Snippet<[TriggerProps]>
}
