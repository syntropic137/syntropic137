import type { ExecutionDetailResponse } from '../types'

/**
 * The token fields of an execution detail payload, split as far as they are known.
 *
 * `total` is authoritative. The four component counts are the part of it that
 * has been attributed to a token type; `inProgressTokens` is the rest, so the
 * five always add up to `total`.
 */
export interface ExecutionTokenTotals {
  total: number
  inputTokens: number
  outputTokens: number
  cacheCreationTokens: number
  cacheReadTokens: number
  /** Counted in `total` but not yet attributed to a token type. */
  inProgressTokens: number
}

/** The subset of the payload these totals are derived from. */
type ExecutionTokenFields = Pick<
  ExecutionDetailResponse,
  | 'total_tokens'
  | 'total_input_tokens'
  | 'total_output_tokens'
  | 'total_cache_creation_tokens'
  | 'total_cache_read_tokens'
>

/**
 * Read an execution's token totals from the response.
 *
 * `total_tokens` is the only token field the API keeps live: it is the larger
 * of the Lane 2 telemetry total and the Lane 1 phase sum, so it climbs while a
 * phase runs. The four component fields are Lane 1 only — `PhaseDetail.running`
 * leaves a running phase's counts at 0 until it completes — so a total
 * re-derived from them reads 0 for the whole of a live run (#1048).
 *
 * The difference between the two is real work whose token type is not known
 * yet. It is reported as `inProgressTokens` rather than dropped, because the
 * alternative is a headline the parts beneath it cannot account for — the same
 * defect as #873, one lane down.
 */
export function executionTokenTotals(execution: ExecutionTokenFields): ExecutionTokenTotals {
  const inputTokens = execution.total_input_tokens
  const outputTokens = execution.total_output_tokens
  const cacheCreationTokens = execution.total_cache_creation_tokens
  const cacheReadTokens = execution.total_cache_read_tokens
  const attributed = inputTokens + outputTokens + cacheCreationTokens + cacheReadTokens

  return {
    total: Math.max(execution.total_tokens, attributed),
    inputTokens,
    outputTokens,
    cacheCreationTokens,
    cacheReadTokens,
    // The API already returns the larger of the two, so this is 0 whenever the
    // breakdown is complete. Deriving it here rather than trusting that keeps a
    // stale or partial payload from rendering a negative row.
    inProgressTokens: Math.max(0, execution.total_tokens - attributed),
  }
}
