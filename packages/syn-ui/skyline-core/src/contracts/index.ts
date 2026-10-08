/**
 * ============================================================================
 *  LOCAL SHIM for @syntropic137/design-contracts. REPLACE ON FIRST PUBLISH.
 * ============================================================================
 *
 * The upstream contracts package is not published yet (the registry returns
 * 404). Until it is, Skyline declares the contract shapes it implements here,
 * mirroring the upstream names (`ButtonContract`, `BadgeContract`, ...) so the
 * swap is an import-path change:
 *
 *   import type { ButtonContract } from '@syn137/skyline-core/contracts'
 *     -> import type { ButtonContract } from '@syntropic137/design-contracts'
 *
 * Rules while the shim lives:
 * - Types only. Nothing here may emit runtime code (contracts cost nothing).
 * - Framework-neutral: no children/slot/snippet types. Each adapter adds its
 *   own content prop (a Svelte `Snippet` in skyline-svelte-v5).
 * - Do not add Skyline-only props here. A Skyline component extends the
 *   contract in its own Props type; this file mirrors upstream only.
 *
 * TODO(#624): delete this module once @syntropic137/design-contracts is
 * published or linked as a submodule under lib/.
 */

/* -------------------------------------------------------------------------- */
/*  Shared vocabulary                                                          */
/* -------------------------------------------------------------------------- */

/** Control height: sm 32px, md 36px, lg 44px (default on coarse pointers). */
export type ContractSize = 'sm' | 'md' | 'lg'

/** Semantic tone. Screens pick a meaning, never a colour. */
export type ContractTone = 'neutral' | 'accent' | 'danger' | 'warning' | 'success'

export type ContractOrientation = 'horizontal' | 'vertical'

/** Every contract a component exposes as `data-state` on its host element. */
export type ContractOpenState = 'open' | 'closed'
export type ContractCheckedState = 'checked' | 'unchecked' | 'indeterminate'

/** Controlled-or-uncontrolled value pair, upstream style. */
export interface ControllableValue<T> {
  value?: T
  defaultValue?: T
  onValueChange?: (value: T) => void
}

export interface ControllableOpen {
  open?: boolean
  defaultOpen?: boolean
  onOpenChange?: (open: boolean) => void
}

/* -------------------------------------------------------------------------- */
/*  Required upstream today                                                    */
/* -------------------------------------------------------------------------- */

export type ButtonVariant = 'solid' | 'outline' | 'ghost'

export interface ButtonContract {
  variant?: ButtonVariant
  size?: ContractSize
  tone?: ContractTone
  type?: 'button' | 'submit' | 'reset'
  disabled?: boolean
  /** Shows a busy state and blocks activation; still focusable. */
  loading?: boolean
  /** Renders as a link when set. */
  href?: string
  /** Required when the button has no visible text (icon-only). */
  'aria-label'?: string
}

export type BadgeVariant = 'solid' | 'soft' | 'outline'

export interface BadgeContract {
  variant?: BadgeVariant
  tone?: ContractTone
  size?: Exclude<ContractSize, 'lg'>
}

/** A single pressed/unpressed button (Skyline draws it as a chip). */
export interface ToggleContract {
  pressed?: boolean
  defaultPressed?: boolean
  onPressedChange?: (pressed: boolean) => void
  size?: ContractSize
  disabled?: boolean
  'aria-label'?: string
}

/** The three components every adapter must implement upstream. */
export interface RequiredComponentContracts {
  Button: ButtonContract
  Badge: BadgeContract
  Toggle: ToggleContract
}

/**
 * The conformance shape an adapter's entry point must satisfy: one component
 * per required contract, typed by the adapter's own component type `C<P>`.
 *
 * e.g. in skyline-svelte-v5:
 *   export const svelteV5ContractAdapter = { Button, Badge, Toggle } satisfies
 *     RequiredComponentAdapter<<P>(props: P) => unknown>
 */
export type RequiredComponentAdapter<Component> = {
  [K in keyof RequiredComponentContracts]: Component
}

/* -------------------------------------------------------------------------- */
/*  Planned upstream (Skyline implements them early)                           */
/* -------------------------------------------------------------------------- */

export interface ToggleGroupContract extends ControllableValue<string[]> {
  /** `single` keeps at most one item pressed; `multiple` any number. */
  type: 'single' | 'multiple'
  orientation?: ContractOrientation
  size?: ContractSize
  disabled?: boolean
  'aria-label'?: string
}

export interface ToggleGroupItemContract {
  value: string
  disabled?: boolean
}

export interface SwitchRootContract {
  checked?: boolean
  defaultChecked?: boolean
  onCheckedChange?: (checked: boolean) => void
  disabled?: boolean
  required?: boolean
  name?: string
  'aria-label'?: string
}

export interface TabsRootContract extends ControllableValue<string> {
  orientation?: ContractOrientation
  /** `automatic` selects on focus; `manual` on activation. */
  activationMode?: 'automatic' | 'manual'
}

export interface TabsTriggerContract {
  value: string
  disabled?: boolean
}

export interface MeterContract {
  value: number
  min?: number
  max?: number
  low?: number
  high?: number
  optimum?: number
  tone?: ContractTone
  'aria-label'?: string
}

export interface ProgressContract {
  /** `null` is indeterminate. */
  value: number | null
  max?: number
  tone?: ContractTone
  'aria-label'?: string
}

export interface CheckboxRootContract {
  checked?: boolean | 'indeterminate'
  defaultChecked?: boolean
  onCheckedChange?: (checked: boolean | 'indeterminate') => void
  disabled?: boolean
  required?: boolean
  name?: string
  value?: string
  'aria-label'?: string
}

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

export interface SelectRootContract extends ControllableValue<string> {
  options: SelectOption[]
  placeholder?: string
  size?: ContractSize
  disabled?: boolean
  name?: string
  'aria-label'?: string
}

export interface PaginationContract {
  /** 1-based. */
  page: number
  pageCount: number
  onPageChange?: (page: number) => void
  /** Pages shown either side of the current one before an ellipsis. */
  siblingCount?: number
  'aria-label'?: string
}

export interface SeparatorContract {
  orientation?: ContractOrientation
  /** Purely visual when true (no separator role). */
  decorative?: boolean
}

export interface LabelContract {
  for?: string
  required?: boolean
}

export interface NavigationMenuItemContract {
  value: string
  label: string
  href: string
  current?: boolean
}

export interface NavigationMenuRootContract extends ControllableValue<string> {
  orientation?: ContractOrientation
  'aria-label'?: string
}

export interface ScrollAreaContract {
  orientation?: ContractOrientation | 'both'
  'aria-label'?: string
}

export interface TooltipRootContract extends ControllableOpen {
  /** ms before opening on hover; focus opens immediately. */
  delayDuration?: number
  side?: 'top' | 'right' | 'bottom' | 'left'
}

export interface CollapsibleRootContract extends ControllableOpen {
  disabled?: boolean
}

export interface AccordionContract extends ControllableValue<string[]> {
  type: 'single' | 'multiple'
  /** With `single`, whether the open item can be closed again. */
  collapsible?: boolean
  disabled?: boolean
}

export interface DialogRootContract extends ControllableOpen {
  modal?: boolean
  'aria-label'?: string
}

export interface AlertDialogRootContract extends ControllableOpen {
  'aria-label'?: string
}

export interface DropdownMenuRootContract extends ControllableOpen {
  modal?: boolean
}

export interface PopoverRootContract extends ControllableOpen {
  modal?: boolean
  side?: 'top' | 'right' | 'bottom' | 'left'
}

export interface CommandRootContract extends ControllableValue<string> {
  /** Current search text. */
  search?: string
  onSearchChange?: (search: string) => void
  /** Client-side filtering; false when results come from a server. */
  shouldFilter?: boolean
  'aria-label'?: string
}
