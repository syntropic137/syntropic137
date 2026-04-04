import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { versionCommand } from "../../src/commands/version.js";

describe("version command", () => {
  beforeEach(() => {
    vi.spyOn(process.stdout, "write").mockReturnValue(true);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function stdout(): string {
    return (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls
      .map((c: unknown[]) => String(c[0]))
      .join("");
  }

  it("prints version string", () => {
    versionCommand.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toContain("Syntropic137");
    expect(out).toMatch(/v\d/);
  });
});
