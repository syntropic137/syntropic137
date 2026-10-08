/**
 * Type-level equality between each union a component renders and the
 * upstream contract union it implements. Inheriting a contract prop is not
 * enough: `size?: ComponentSize` widens silently when upstream does. These
 * assertions fail when an implementation accepts a different set than the
 * contract (narrower or wider), and the exhaustive lookups in each
 * component's `variants.ts` fail when a member has no styling.
 *
 * Plain .ts over types.ts files only, so both svelte-check and
 * `tsc --noEmit` (skyline-svelte-v5 `typecheck`) check it.
 */
import type {
  ButtonContract,
  ButtonVariant,
  BadgeVariant,
  CheckedState,
  ComponentSize,
  ComponentTone,
  DataAlign,
  DataOrientation,
  DataSide,
  ScrollAreaType,
} from '@syn137/skyline-core/contracts'
import type { BadgeProps } from './components/Badge/types'
import type { ButtonProps, SkylineButtonVariant } from './components/Button/types'
import type { CheckboxProps } from './components/Checkbox/types'
import type { InputProps, TextareaProps } from './components/Input/types'
import type { MeterProps } from './components/Meter/types'
import type { NavigationMenuProps } from './components/NavigationMenu/types'
import type { PopoverProps } from './components/Popover/types'
import type { ProgressProps } from './components/Progress/types'
import type { ScrollAreaProps } from './components/ScrollArea/types'
import type { SelectProps } from './components/Select/types'
import type { SeparatorProps } from './components/Separator/types'
import type { TabsProps } from './components/Tabs/types'
import type { ToggleGroupProps } from './components/ToggleGroup/types'
import type { ToggleProps } from './components/Toggle/types'
import type { TooltipProps } from './components/Tooltip/types'

/** True only when A and B are the same type (not merely mutually assignable). */
export type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false
export type Expect<T extends true> = T
type Opt<T> = NonNullable<T>

export type SvelteV5UnionConformance = [
  // Button: Skyline's variants are a documented superset of upstream's.
  Expect<Equal<Opt<ButtonProps['size']>, ComponentSize>>,
  Expect<Equal<Opt<ButtonProps['variant']>, SkylineButtonVariant | ButtonVariant>>,
  Expect<Equal<Opt<ButtonProps['tone']>, ComponentTone>>,
  Expect<Equal<ButtonProps['type'], ButtonContract['type']>>,
  // Badge (size is Skyline-only: sm and md).
  Expect<Equal<Opt<BadgeProps['variant']>, BadgeVariant>>,
  Expect<Equal<Opt<BadgeProps['tone']>, ComponentTone>>,
  Expect<Equal<Opt<BadgeProps['size']>, Exclude<ComponentSize, 'lg'>>>,
  // Sizes.
  Expect<Equal<Opt<ToggleProps['size']>, ComponentSize>>,
  Expect<Equal<Opt<ToggleGroupProps['size']>, ComponentSize>>,
  Expect<Equal<Opt<SelectProps['size']>, ComponentSize>>,
  Expect<Equal<Opt<InputProps['size']>, ComponentSize>>,
  Expect<Equal<Opt<TextareaProps['size']>, ComponentSize>>,
  // Tones.
  Expect<Equal<Opt<MeterProps['tone']>, ComponentTone>>,
  Expect<Equal<Opt<ProgressProps['tone']>, ComponentTone>>,
  // Orientation (Scroll Area adds Skyline's 'both').
  Expect<Equal<Opt<TabsProps['orientation']>, DataOrientation>>,
  Expect<Equal<Opt<SeparatorProps['orientation']>, DataOrientation>>,
  Expect<Equal<Opt<NavigationMenuProps['orientation']>, DataOrientation>>,
  Expect<Equal<Opt<ToggleGroupProps['orientation']>, DataOrientation>>,
  Expect<Equal<Opt<ScrollAreaProps['orientation']>, DataOrientation | 'both'>>,
  Expect<Equal<Opt<ScrollAreaProps['type']>, ScrollAreaType>>,
  // Floating placement.
  Expect<Equal<Opt<TooltipProps['side']>, DataSide>>,
  Expect<Equal<Opt<TooltipProps['align']>, DataAlign>>,
  Expect<Equal<Opt<PopoverProps['side']>, DataSide>>,
  Expect<Equal<Opt<PopoverProps['align']>, DataAlign>>,
  // Checked state.
  Expect<Equal<Opt<CheckboxProps['checked']>, CheckedState>>,
]
