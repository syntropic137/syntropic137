import { expect, it, vi } from "vitest";
import { RATE_LIMIT_POLICY, retryAfterMs, retryRateLimited, type RateLimitPolicy } from "../../src/client/rate-limit.js";

const now = Date.parse("2026-11-11T00:00:00Z");
const policy: RateLimitPolicy = { ...RATE_LIMIT_POLICY, now: () => now, sleep: vi.fn(async () => undefined) };

it("reads Retry-After as seconds or an HTTP-date, defaulting and clamping", () => {
  expect(retryAfterMs("3", policy)).toBe(3_000);
  expect(retryAfterMs(new Date(now + 5_000).toUTCString(), policy)).toBe(5_000);
  expect(retryAfterMs(new Date(now - 5_000).toUTCString(), policy)).toBe(0);
  expect(retryAfterMs(null, policy)).toBe(1_000);
  expect(retryAfterMs("soon", policy)).toBe(1_000);
  expect(retryAfterMs("-4", policy)).toBe(1_000);
  expect(retryAfterMs("3600", policy)).toBe(30_000);
  expect(retryAfterMs(new Date(now + 3_600_000).toUTCString(), policy)).toBe(30_000);
});

it("returns the first non-429 result without waiting", async () => {
  const send = vi.fn(async () => ({ response: new Response(null, { status: 503 }) }));
  const result = await retryRateLimited(send, () => new Error("exhausted"), { ...policy, sleep: vi.fn() });
  expect(result.response.status).toBe(503);
  expect(send).toHaveBeenCalledTimes(1);
});
