import { describe, expect, it } from 'vitest'

import {
  exactUsdToNumber,
  exactUsdToString,
  isVisibleCost,
  parseExactUsd,
  sumExactUsd,
} from '../exactUsd'

// Real values from GET /executions/exec-105b88d56234 (beta.7).
const LIVE_TOTAL = '0.43809100000000005'
const LIVE_OPUS = '0.30566780000000005'
const LIVE_SOL = '0.1324232'

function parse(value: string | number): bigint {
  const parsed = parseExactUsd(value)
  if (parsed === null) throw new Error(`unparseable: ${value}`)
  return parsed
}

describe('parseExactUsd', () => {
  it('parses decimal strings exactly', () => {
    expect(exactUsdToString(parse(LIVE_OPUS))).toBe('0.30566780000000005')
    expect(exactUsdToString(parse('12'))).toBe('12')
    expect(exactUsdToString(parse('.5'))).toBe('0.5')
    expect(exactUsdToString(parse('-0.25'))).toBe('-0.25')
  })

  it('parses exponent notation, which Number#toString emits for tiny values', () => {
    expect(exactUsdToString(parse(1e-7))).toBe('0.0000001')
    expect(exactUsdToString(parse('2.5E+2'))).toBe('250')
  })

  it('rejects anything that is not a finite decimal rather than reading it as 0', () => {
    for (const bad of ['', 'abc', '1.2.3', '.', 'NaN', Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(parseExactUsd(bad)).toBeNull()
    }
  })

  it('rounds past the 18th decimal place half away from zero', () => {
    expect(exactUsdToString(parse('0.0000000000000000005'))).toBe('0.000000000000000001')
    expect(exactUsdToString(parse('0.0000000000000000004'))).toBe('0')
  })
})

describe('exact subtraction of the live execution', () => {
  it('leaves exactly nothing where float subtraction leaves ~1e-17', () => {
    // The float version of this is what rendered "not yet attributed $0.000000".
    expect(Number(LIVE_TOTAL) - (Number(LIVE_OPUS) + Number(LIVE_SOL))).not.toBe(0)

    const remainder = parse(LIVE_TOTAL) - sumExactUsd([parse(LIVE_OPUS), parse(LIVE_SOL)])
    expect(remainder).toBe(0n)
    expect(isVisibleCost(remainder)).toBe(false)
  })
})

describe('isVisibleCost', () => {
  it('hides what formatCost would print as $0.000000', () => {
    expect(isVisibleCost(parse('0.0000004'))).toBe(false)
    expect(isVisibleCost(parse('-0.5'))).toBe(false)
  })

  it('shows anything that rounds to at least one micro-dollar', () => {
    expect(isVisibleCost(parse('0.0000005'))).toBe(true)
    expect(isVisibleCost(parse('0.12'))).toBe(true)
  })
})

describe('exactUsdToNumber', () => {
  it('returns the nearest double to the exact value', () => {
    expect(exactUsdToNumber(parse('0.1324232'))).toBe(0.1324232)
  })
})
