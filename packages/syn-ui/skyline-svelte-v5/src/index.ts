/**
 * @syn137/skyline-svelte-v5: base components.
 *
 * Phase 1 fills this file. One line per component, alphabetical within its
 * group, re-exported from ./components/<Name>/:
 *
 *   export { default as Button } from './components/Button/Button.svelte'
 *   export type { ButtonProps } from './components/Button/types'
 *
 * Contract components (props extend the upstream contract):
 *   Button, Badge, Toggle (required) - Toggle Group, Switch, Tabs, Meter,
 *   Progress, Checkbox, Select, Pagination, Separator, Label, Navigation Menu,
 *   Scroll Area, Tooltip, Collapsible, Accordion, Dialog, Alert Dialog,
 *   Dropdown Menu, Popover, Command.
 * Skyline-only components (no contract yet):
 *   Card, Tag, Input, Breadcrumbs, Stat, Callout, Empty State, Skeleton.
 *
 * Conformance: `svelteV5ContractAdapter` (bottom of this file) covers every
 * upstream required contract, and `SvelteV5ContractConformance` checks that
 * each of those components accepts its contract's props.
 *
 * Patterns (App Shell, Skyline, Run Row, ...) export from './patterns'.
 */
export { default as VisuallyHidden } from './internal/VisuallyHidden.svelte'

// ---- Contract components (props extend @syn137/skyline-core/contracts) ----
export { default as Accordion } from './components/Accordion/Accordion.svelte'
export type { AccordionProps, AccordionItem } from './components/Accordion/types'
export { default as AlertDialog } from './components/AlertDialog/AlertDialog.svelte'
export type { AlertDialogProps } from './components/AlertDialog/types'
export { default as Badge } from './components/Badge/Badge.svelte'
export type { BadgeProps } from './components/Badge/types'
export { default as Button } from './components/Button/Button.svelte'
export type { ButtonProps } from './components/Button/types'
export { default as Checkbox } from './components/Checkbox/Checkbox.svelte'
export type { CheckboxProps } from './components/Checkbox/types'
export { default as Collapsible } from './components/Collapsible/Collapsible.svelte'
export type { CollapsibleProps, CollapsibleTriggerProps } from './components/Collapsible/types'
export { default as Command } from './components/Command/Command.svelte'
export { default as CommandDialog } from './components/Command/CommandDialog.svelte'
export type { CommandProps, CommandDialogProps, CommandGroup, CommandItem } from './components/Command/types'
export { default as Dialog } from './components/Dialog/Dialog.svelte'
export type { DialogProps, DialogSize } from './components/Dialog/types'
export { default as DropdownMenu } from './components/DropdownMenu/DropdownMenu.svelte'
export type { DropdownMenuProps, MenuEntry, MenuItem, MenuLabel, MenuSeparator } from './components/DropdownMenu/types'
export { default as Label } from './components/Label/Label.svelte'
export type { LabelProps } from './components/Label/types'
export { default as Meter } from './components/Meter/Meter.svelte'
export type { MeterProps, MeterSeries } from './components/Meter/types'
export { default as NavigationMenu } from './components/NavigationMenu/NavigationMenu.svelte'
export type { NavigationMenuProps, NavigationMenuItem } from './components/NavigationMenu/types'
export { default as Pagination } from './components/Pagination/Pagination.svelte'
export type { PaginationProps } from './components/Pagination/types'
export { default as Popover } from './components/Popover/Popover.svelte'
export type { PopoverProps } from './components/Popover/types'
export { default as Progress } from './components/Progress/Progress.svelte'
export type { ProgressProps } from './components/Progress/types'
export { default as ScrollArea } from './components/ScrollArea/ScrollArea.svelte'
export type { ScrollAreaProps } from './components/ScrollArea/types'
export { default as Select } from './components/Select/Select.svelte'
export type { SelectProps } from './components/Select/types'
export { default as Separator } from './components/Separator/Separator.svelte'
export type { SeparatorProps } from './components/Separator/types'
export { default as Switch } from './components/Switch/Switch.svelte'
export type { SwitchProps } from './components/Switch/types'
export { default as Tabs } from './components/Tabs/Tabs.svelte'
export type { TabsProps, TabsItem } from './components/Tabs/types'
export { default as Toggle } from './components/Toggle/Toggle.svelte'
export type { ToggleProps } from './components/Toggle/types'
export { default as ToggleGroup } from './components/ToggleGroup/ToggleGroup.svelte'
export type { ToggleGroupProps, ToggleGroupItem } from './components/ToggleGroup/types'
export { default as Tooltip } from './components/Tooltip/Tooltip.svelte'
export type { TooltipProps } from './components/Tooltip/types'

// ---- Skyline-only components (no upstream contract yet) ----
export { default as Breadcrumbs } from './components/Breadcrumbs/Breadcrumbs.svelte'
export type { BreadcrumbsProps } from './components/Breadcrumbs/types'
export { default as Callout } from './components/Callout/Callout.svelte'
export type { CalloutProps, CalloutTone } from './components/Callout/types'
export { default as Card } from './components/Card/Card.svelte'
export type { CardProps, CardVariant, CardPadding } from './components/Card/types'
export { default as CopyButton } from './components/CopyButton/CopyButton.svelte'
export type { CopyButtonProps } from './components/CopyButton/types'
export { writeClipboard } from './components/CopyButton/clipboard'
export { default as EmptyState } from './components/EmptyState/EmptyState.svelte'
export type { EmptyStateProps } from './components/EmptyState/types'
export { default as Input } from './components/Input/Input.svelte'
export { default as Textarea } from './components/Input/Textarea.svelte'
export type { InputProps, TextareaProps, FieldMessageTone } from './components/Input/types'
export { default as Skeleton } from './components/Skeleton/Skeleton.svelte'
export type { SkeletonProps, SkeletonVariant } from './components/Skeleton/types'
export { default as Stat } from './components/Stat/Stat.svelte'
export type { StatProps, StatSize } from './components/Stat/types'
export { default as Tag } from './components/Tag/Tag.svelte'
export type { TagProps, TagVariant, TagAgent } from './components/Tag/types'

// ---- Shared overlay plumbing for patterns built on these components ----
export type { TriggerProps } from './components/_internal/trigger'

// ---- Upstream conformance: the required contracts, type-checked ----
import type { RequiredComponentAdapter, RequiredComponentContracts } from '@syn137/skyline-core/contracts'
import BadgeComponent from './components/Badge/Badge.svelte'
import ButtonComponent from './components/Button/Button.svelte'
import ToggleComponent from './components/Toggle/Toggle.svelte'
import type { BadgeProps as BadgeComponentProps } from './components/Badge/types'
import type { ButtonProps as ButtonComponentProps } from './components/Button/types'
import type { ToggleProps as ToggleComponentProps } from './components/Toggle/types'
// The adapter covers every required contract (upstream keys: button, badge, toggle).
export const svelteV5ContractAdapter = { button: ButtonComponent, badge: BadgeComponent, toggle: ToggleComponent } satisfies RequiredComponentAdapter
// Each required component accepts every prop of its contract. Checked this way round because
// Skyline props are a superset (Button also takes Skyline's solid/outline variants and a tone).
// Per key, because Svelte's HTML attribute types carry a symbol index signature (attachments).
type AcceptsContract<Props, Contract> = {
  [K in keyof Contract]-?: K extends keyof Props ? ([Contract[K]] extends [Props[K]] ? true : false) : false
}[keyof Contract] extends true
  ? true
  : false
type AssertTrue<T extends true> = T
export type SvelteV5ContractConformance = [
  AssertTrue<AcceptsContract<ButtonComponentProps, RequiredComponentContracts['button']>>,
  AssertTrue<AcceptsContract<BadgeComponentProps, RequiredComponentContracts['badge']>>,
  AssertTrue<AcceptsContract<ToggleComponentProps, RequiredComponentContracts['toggle']>>,
]
