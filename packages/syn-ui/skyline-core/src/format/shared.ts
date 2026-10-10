/** Placeholder for an unknown value: an em dash, never "0" or "NaN". */
export const UNKNOWN = '—'

/** A finite number from a number or a decimal string (the API serialises Decimal as string). */
export function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'string' ? Number(value) : value
  return Number.isFinite(n) ? n : null
}

/** A timestamp in ms from an ISO string, epoch ms or Date; null when unparseable. */
export function toTime(value: string | number | Date | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const t = value instanceof Date ? value.getTime() : typeof value === 'number' ? value : Date.parse(value)
  return Number.isFinite(t) ? t : null
}
