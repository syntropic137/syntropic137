/**
 * Resend a request the gateway rate-limited (HTTP 429), waiting as long as it asks.
 *
 * Only 429 is retried: it is the one status that says "the same request will
 * work later". Callers must only pass requests that are safe to resend
 * unchanged, i.e. reads.
 */

export interface RateLimitPolicy {
  /** Total requests sent, the first included, before giving up. */
  attempts: number;
  /** Wait when Retry-After is absent or unparseable. */
  defaultWaitMs: number;
  /** Upper bound on any single wait, whatever Retry-After asks for. */
  maxWaitMs: number;
  sleep: (ms: number) => Promise<void>;
  now: () => number;
}

/**
 * The policy commands use. Its `sleep` and `now` are read at call time, so a
 * test can replace them with `vi.spyOn(RATE_LIMIT_POLICY, "sleep")`.
 */
export const RATE_LIMIT_POLICY: RateLimitPolicy = {
  attempts: 6,
  defaultWaitMs: 1_000,
  maxWaitMs: 30_000,
  sleep: ms => new Promise(resolve => setTimeout(resolve, ms)),
  now: () => Date.now(),
};

/** Retry-After as milliseconds: delay-seconds or an HTTP-date, clamped to the policy. */
export function retryAfterMs(header: string | null, policy: RateLimitPolicy): number {
  const value = header?.trim() ?? "";
  let wait = policy.defaultWaitMs;
  if (/^\d+$/.test(value)) wait = Number(value) * 1_000;
  else if (value !== "" && !Number.isNaN(Date.parse(value))) wait = Math.max(0, Date.parse(value) - policy.now());
  return Math.min(wait, policy.maxWaitMs);
}

/**
 * Send, and resend after each 429 until a non-429 answer or `policy.attempts`
 * requests. Any non-429 result is returned as is. When every attempt was
 * rate-limited, throws what `exhausted(attempts)` builds, so the caller can say
 * how to resume.
 */
export async function retryRateLimited<T extends { response: Response }>(
  send: () => Promise<T>,
  exhausted: (attempts: number) => Error,
  policy: RateLimitPolicy = RATE_LIMIT_POLICY,
): Promise<T> {
  for (let attempt = 1; ; attempt += 1) {
    const result = await send();
    if (result.response.status !== 429) return result;
    if (attempt >= policy.attempts) throw exhausted(attempt);
    await policy.sleep(retryAfterMs(result.response.headers.get("Retry-After"), policy));
  }
}
