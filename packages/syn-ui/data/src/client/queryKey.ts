/**
 * Query keys and parameter snapshots for the query cache (ADR-074).
 *
 * A key is the resource name plus a type-tagged encoding of its params, so
 * values that would print alike stay distinct: `[undefined]` vs `[null]`,
 * `'1'` vs `1`, URLSearchParams vs a string array, and `a=b,c` vs `a,b=c`
 * (pairs are encoded as tuples, never `k=v` text). Object key order and
 * undefined object fields do not matter; array order does.
 */
type Encoded = string | number | boolean | null | Encoded[]

const SCALARS: Record<string, (v: never) => Encoded> = {
  string: (v: string) => ['s', v],
  number: (v: number) => ['d', String(v)], // String keeps NaN / -0 / Infinity apart from null
  boolean: (v: boolean) => ['b', v],
  bigint: (v: bigint) => ['i', v.toString()],
}

function encode(value: unknown): Encoded {
  if (value === undefined) return ['u']
  if (value === null) return ['n']
  const scalar = SCALARS[typeof value]
  if (scalar) return scalar(value as never)
  if (typeof value !== 'object') return ['x', String(value)] // functions and symbols: not real params
  return encodeObject(value)
}

function encodeObject(value: object): Encoded {
  if (value instanceof URLSearchParams) {
    const pairs = [...value].map(([k, v]): Encoded => [k, v])
    return ['q', pairs.sort((x, y) => cmp(JSON.stringify(x), JSON.stringify(y)))]
  }
  if (value instanceof Date) return ['t', value.toISOString()]
  if (Array.isArray(value)) return ['a', value.map(encode)]
  const obj = value as Record<string, unknown>
  const keys = Object.keys(obj).filter((k) => obj[k] !== undefined).sort(cmp)
  return ['o', keys.map((k): Encoded => [k, encode(obj[k])])]
}

const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0)

/** "getExecution" + ["abc"] -> 'getExecution:["a",[["s","abc"]]]'. */
export function queryKey(name: string, params: readonly unknown[]): string {
  return `${name}:${JSON.stringify(encode(params))}`
}

/** A copy of `params` the caller can no longer mutate under the cache. */
export function snapshotParams(params: readonly unknown[]): readonly unknown[] {
  return Object.freeze(params.map(snapshot))
}

function snapshot(value: unknown): unknown {
  if (value instanceof URLSearchParams) return new URLSearchParams(value)
  if (value instanceof Date) return new Date(value.getTime())
  if (Array.isArray(value)) return Object.freeze(value.map(snapshot))
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(value)) out[k] = snapshot(v)
    return Object.freeze(out)
  }
  return value
}
