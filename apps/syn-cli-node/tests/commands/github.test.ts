/**
 * `syn github repos` against responses recorded from the real route
 * (apps/syn-api/tests/test_github_repos_lookup.py), so a GitHub failure the
 * API reports is never printed as "no repositories".
 */
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { githubGroup } from "../../src/commands/github.js";

const fixture = JSON.parse(readFileSync(
  new URL("../../../syn-api/tests/fixtures/github_repos_lookup.json", import.meta.url), "utf8",
)) as Record<"confirmed_empty" | "installation_lookup_failed" | "one_installation_failed", unknown>;

const repos = githubGroup.commands.get("repos")!;

function output(stream: NodeJS.WriteStream): string {
  return (stream.write as ReturnType<typeof vi.fn>).mock.calls.map((c: unknown[]) => String(c[0])).join("");
}

async function run(body: unknown): Promise<string> {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })));
  await repos.handler({ positionals: [], values: {} });
  return output(process.stdout) + output(process.stderr);
}

describe("github repos", () => {
  beforeEach(() => {
    vi.spyOn(process.stdout, "write").mockReturnValue(true);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("says none are accessible only when GitHub answered", async () => {
    expect(await run(fixture.confirmed_empty)).toContain("No accessible repositories found.");
  });

  it("says access is unknown when the installation lookup failed", async () => {
    const printed = await run(fixture.installation_lookup_failed);
    expect(printed).toContain("App access is unknown");
    expect(printed).not.toContain("No accessible repositories found.");
  });

  it("lists what it found and warns when one installation failed", async () => {
    const printed = await run(fixture.one_installation_failed);
    expect(printed).toContain("acme/payments");
    expect(printed).toContain("GitHub failed for some installations");
  });
});
