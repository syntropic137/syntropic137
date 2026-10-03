/**
 * A known route that 404s with the router's own body names the server build
 * and says it predates the feature (#1501 B). Each case goes through a real
 * typed client and `unwrap`, so what is asserted is the message a command
 * would throw, not the middleware's return value.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { explainMissingRoutes } from "../../src/client/missing-route.js";
import type { ServerBuild } from "../../src/client/server-build.js";
import { createTypedClient, unwrap } from "../../src/client/typed.js";

const DEPLOYMENT = "http://syn.example";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const reported: ServerBuild = {
  kind: "reported",
  build: { version: "0.33.0b5", image_tag: null, commit: null, version_status: "installed" },
};

/** The message `syn execution sessions` would throw against a server that
 * answers the inventory route with `inventory`, and /version as `build`. */
async function inventoryError(inventory: Response, build: ServerBuild): Promise<string> {
  const serverBuild = vi.fn(async () => build);
  vi.stubGlobal("fetch", async () => inventory);
  const client = createTypedClient();
  client.use(explainMissingRoutes(serverBuild, DEPLOYMENT));
  const result = await client.GET("/executions/{execution_id}/session-inventory", {
    params: { path: { execution_id: "exec-1" } },
  });
  expect(result.response.status).toBe(404);
  try {
    unwrap(result, "Failed to read session inventory");
  } catch (err) {
    return (err as Error).message;
  }
  throw new Error("unwrap did not throw");
}

describe("explainMissingRoutes", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("names the reported build and says the server predates the feature", async () => {
    const message = await inventoryError(json({ detail: "Not Found" }, 404), reported);
    expect(message).toBe(
      "Failed to read session inventory: syn-api 0.33.0b5 at http://syn.example has no " +
        "GET /executions/{execution_id}/session-inventory; this server predates the feature. " +
        "Upgrade the server to use this command.",
    );
  });

  it("does not invent a version when the server has no /version either", async () => {
    const message = await inventoryError(json({ detail: "Not Found" }, 404), { kind: "no-version-route" });
    expect(message).toContain("predates the feature");
    expect(message).toContain("no GET /version");
    expect(message).not.toMatch(/mismatch|differ/i);
  });

  it("says why the version is unknown when /version did not answer", async () => {
    const message = await inventoryError(json({ detail: "Not Found" }, 404), {
      kind: "unanswered",
      reason: "no answer within 1500ms",
    });
    expect(message).toContain("predates the feature");
    expect(message).toContain("Its version could not be read: no answer within 1500ms.");
  });

  it("leaves a handler's own 404 alone: the route exists, the thing does not", async () => {
    const message = await inventoryError(json({ detail: "Execution exec-1 not found" }, 404), reported);
    expect(message).toBe("Failed to read session inventory: Execution exec-1 not found");
  });

  it("never touches GET /version itself, and never asks for the build to explain it", async () => {
    const serverBuild = vi.fn(async () => reported);
    vi.stubGlobal("fetch", async () => json({ detail: "Not Found" }, 404));
    const client = createTypedClient();
    client.use(explainMissingRoutes(serverBuild, DEPLOYMENT));
    const result = await client.GET("/version");
    expect(result.response.status).toBe(404);
    expect(result.error).toEqual({ detail: "Not Found" });
    expect(serverBuild).not.toHaveBeenCalled();
  });

  it("does not ask for the build on a response that is not a 404", async () => {
    const serverBuild = vi.fn(async () => reported);
    vi.stubGlobal("fetch", async () => json({ detail: "Not Found" }, 403));
    const client = createTypedClient();
    client.use(explainMissingRoutes(serverBuild, DEPLOYMENT));
    const result = await client.GET("/executions/{execution_id}", { params: { path: { execution_id: "e" } } });
    expect(result.error).toEqual({ detail: "Not Found" });
    expect(serverBuild).not.toHaveBeenCalled();
  });
});
