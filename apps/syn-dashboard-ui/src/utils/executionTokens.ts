import type { ExecutionDetailResponse, PhaseExecutionDetail } from '../types'

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
 * `total_tokens` is the only token field the API keeps live throughout: it is
 * the larger of the Lane 2 telemetry total and the Lane 1 phase sum, so it
 * climbs while a phase runs. Of the four component fields, input and output are
 * strictly Lane 1 — `PhaseDetail.running` leaves a running phase's counts at 0
 * until it completes — while the two cache fields may already carry a live
 * session-cost substitution (`_load_session_cost` fills them in when the Lane 1
 * pair reads 0). Either way the components are incomplete mid-run, so a total
 * re-derived from them reads short for the whole of a live run (#1048).
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

/** The subset of a phase these totals are derived from. */
type PhaseTokenFields = Pick<
  PhaseExecutionDetail,
  'status' | 'input_tokens' | 'output_tokens' | 'cache_creation_tokens' | 'cache_read_tokens'
>

/**
 * One phase's token counts, and whether they can be read as a count at all.
 *
 * Lane 1 writes a phase's counts when the phase completes, so a running phase
 * reports 0 for work that is demonstrably happening. `settled` separates the
 * two states a bare 0 conflates: not counted yet, versus counted and genuinely
 * zero. There is no live per-phase field to read instead — only the execution
 * total is live — so a caller that renders an unsettled figure must say so.
 */
export interface PhaseTokenTotals {
  total: number
  inputTokens: number
  outputTokens: number
  cacheCreationTokens: number
  cacheReadTokens: number
  /** False while `total` is a lower bound rather than the phase's count. */
  settled: boolean
}

/**
 * Read one phase's token counts from the response.
 *
 * The counts are returned even when unsettled rather than blanked: the API
 * substitutes a live session-cost reading for the two cache fields when the
 * Lane 1 pair still reads 0 (`_load_session_cost`), so a running phase can
 * carry a real partial figure. `settled` marks it as the lower bound it is.
 */
export function phaseTokenTotals(phase: PhaseTokenFields): PhaseTokenTotals {
  const inputTokens = phase.input_tokens
  const outputTokens = phase.output_tokens
  const cacheCreationTokens = phase.cache_creation_tokens ?? 0
  const cacheReadTokens = phase.cache_read_tokens ?? 0

  return {
    total: inputTokens + outputTokens + cacheCreationTokens + cacheReadTokens,
    inputTokens,
    outputTokens,
    cacheCreationTokens,
    cacheReadTokens,
    // 'pending' is settled: a phase that has not started really has used no
    // tokens. Only 'running' has counts the API has not written down yet.
    settled: phase.status !== 'running',
  }
}
