import type { Snippet } from 'svelte'
import type { HTMLInputAttributes, HTMLTextareaAttributes } from 'svelte/elements'
import type { ContractSize } from '@syn137/skyline-core/contracts'

/** Tone of the line under a field: an error (coral), a caution (amber) or plain help. */
export type FieldMessageTone = 'danger' | 'warning' | 'neutral'

interface FieldProps {
  size?: ContractSize
  /** Marks the field invalid (coral border, aria-invalid). Implied by `messageTone="danger"` while a `message` shows. */
  invalid?: boolean
  /** Line under the field; linked with aria-describedby. */
  message?: string
  messageTone?: FieldMessageTone
}

/**
 * Input (CompActions "Input, Select, Label"; no upstream contract yet).
 * Fields sit on the ground colour. `type="search"` gets the search glyph.
 * Bind the value with `bind:value`.
 */
export interface InputProps extends FieldProps, Omit<HTMLInputAttributes, 'size' | 'children'> {
  value?: string | number | null
  /** Leading adornment (icon or "Sort"-style prefix). */
  leading?: Snippet
  trailing?: Snippet
}

/** Textarea: the multi-line field (Task, Topic). */
export interface TextareaProps extends FieldProps, Omit<HTMLTextareaAttributes, 'children'> {
  value?: string | null
}
