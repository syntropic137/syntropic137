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
 * Once Button, Badge and Toggle exist, add the conformance entry:
 *
 *   import type { RequiredComponentAdapter } from '@syn137/skyline-core/contracts'
 *   export const svelteV5ContractAdapter = { Button, Badge, Toggle } satisfies
 *     RequiredComponentAdapter<Component<any>>
 *
 * Patterns (App Shell, Skyline, Run Row, ...) export from './patterns'.
 */
export { default as VisuallyHidden } from './internal/VisuallyHidden.svelte'
