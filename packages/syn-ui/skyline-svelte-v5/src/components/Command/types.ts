import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'
import type { CommandRootContract } from '@syn137/skyline-core/contracts'
import type { CommandFilterItem } from '@syn137/skyline-core/state'

export interface CommandItem extends CommandFilterItem {
  /** Unique within the palette. */
  id: string
  /** Mono text on the right ("research-workflow-v2"). */
  meta?: string
  /** Key hint ("G E"). */
  shortcut?: string
  icon?: Snippet
  href?: string
  onSelect?: () => void
}

export interface CommandGroup {
  heading: string
  items: CommandItem[]
}

/**
 * Command (CommandRootContract). CompNav "command · ⌘K": search on top,
 * grouped results (Workflows, Actions, Go to), the active row highlighted
 * with a ↵ hint.
 *
 * A combobox over a listbox: focus stays in the input, arrows move the
 * active row (aria-activedescendant), Enter selects. Filtering is client-
 * side unless `shouldFilter` is false (server results). Use CommandDialog
 * for the ⌘K palette.
 */
export interface CommandProps extends CommandRootContract, Omit<HTMLAttributes<HTMLDivElement>, keyof CommandRootContract | 'children'> {
  groups: CommandGroup[]
  placeholder?: string
  /** Text when nothing matches. */
  empty?: string
  loading?: boolean
  /** Shows the "esc" hint in the input row (inside a dialog). */
  escHint?: boolean
  onSelect?: (item: CommandItem) => void
  /** Follows an item's `href`. Default: a full page load; the app passes its router. */
  onNavigate?: (href: string) => void
}

/** CommandDialog: the ⌘K palette. Same props as Command, plus the open state. */
export interface CommandDialogProps extends CommandProps {
  open?: boolean
  onOpenChange?: (open: boolean) => void
}
