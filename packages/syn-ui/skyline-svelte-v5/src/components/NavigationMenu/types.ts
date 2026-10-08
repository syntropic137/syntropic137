import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'
import type { NavigationMenuItemContract, NavigationMenuRootContract } from '@syn137/skyline-core/contracts'

export interface NavigationMenuItem extends NavigationMenuItemContract {
  icon?: Snippet
  /** Mono figure shown in the More menu ("65"). */
  meta?: string
}

/**
 * Navigation Menu (NavigationMenuRootContract). CompNav, in both forms:
 *
 * - `variant="capsule"`: the top capsule from 48rem up (TopNav board).
 * - `variant="dock"`: the phone's floating dock (PhoneDock board), with
 *   `more` items behind a More menu.
 *
 * `value` names the current section (or set `current` on an item); it gets
 * aria-current="page". Links are plain anchors so the app router can
 * intercept them.
 */
export interface NavigationMenuProps extends NavigationMenuRootContract, Omit<HTMLAttributes<HTMLElement>, keyof NavigationMenuRootContract | 'children'> {
  items: NavigationMenuItem[]
  variant?: 'capsule' | 'dock'
  /** Dock only: sections behind the More button. */
  more?: NavigationMenuItem[]
  moreLabel?: string
  moreIcon?: Snippet
}
