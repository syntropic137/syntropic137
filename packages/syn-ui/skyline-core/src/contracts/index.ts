/**
 * Upstream component contracts, re-exported for Skyline.
 *
 * Source of truth: `@syntropic137/design-contracts` (pinned exactly in
 * package.json). Components import from `@syn137/skyline-core/contracts` so
 * the pin lives in one place.
 *
 * Rules:
 * - Types only (`export type`): contracts cost nothing at runtime.
 * - Do not add Skyline-only props here. A Skyline component extends the
 *   contract in its own Props type and documents any divergence there.
 * - The aliases below keep the names the components were written against;
 *   new code should use the upstream names.
 */
import type {
  CheckedState,
  ComponentSize,
  ComponentTone,
  DataOrientation,
  OpenContract,
  SelectItemContract,
  ValueContract,
} from '@syntropic137/design-contracts'

export type * from '@syntropic137/design-contracts'

/** Upstream `ComponentSize` (sm 32px, md 36px, lg 44px). */
export type ContractSize = ComponentSize
/** Upstream `ComponentTone`. Screens pick a meaning, never a colour. */
export type ContractTone = ComponentTone
/** Upstream `DataOrientation`. */
export type ContractOrientation = DataOrientation
/** Upstream `CheckedState` (`boolean | 'indeterminate'`). */
export type ContractCheckedState = CheckedState
/** Upstream `ValueContract<T>`: controlled-or-uncontrolled value. */
export type ControllableValue<T> = ValueContract<T>
/** Upstream `OpenContract`: controlled-or-uncontrolled open state. */
export type ControllableOpen = OpenContract
/** Upstream `SelectItemContract`. */
export type SelectOption = SelectItemContract

/** Local: upstream has no `data-state` open/closed type (`OpenContract` is the props shape). */
export type ContractOpenState = 'open' | 'closed'

/** Local: upstream 0.1.0 has no Toggle Group item contract. */
export interface ToggleGroupItemContract {
  value: string
  disabled?: boolean
}
