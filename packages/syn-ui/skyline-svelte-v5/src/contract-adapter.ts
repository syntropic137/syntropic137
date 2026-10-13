/**
 * Contract adapter for @syntropic137/design-contracts.
 *
 * `svelteV5ContractAdapter` covers every upstream required contract, and
 * `SvelteV5ContractConformance` checks that each of those components accepts
 * its contract's props. This file name is the one the published
 * `design-system-verify` gate looks for (check D); the package index
 * re-exports both, so `@syn137/skyline-svelte-v5` is the import path.
 * Union-level equality: ./contract-unions.ts.
 */
import type { ComponentProps } from 'svelte'
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
  // The same, against the props each .svelte file actually declares in $props(),
  // so a component cannot drop a contract prop its types.ts still lists.
  AssertTrue<AcceptsContract<ComponentProps<typeof ButtonComponent>, RequiredComponentContracts['button']>>,
  AssertTrue<AcceptsContract<ComponentProps<typeof BadgeComponent>, RequiredComponentContracts['badge']>>,
  AssertTrue<AcceptsContract<ComponentProps<typeof ToggleComponent>, RequiredComponentContracts['toggle']>>,
]
