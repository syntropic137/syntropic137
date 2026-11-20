import { afterEach, describe, expect, it, vi } from "vitest";
import { printUnpricedNote } from "../../src/output/console.js";

describe("printUnpricedNote", () => {
  afterEach(() => vi.restoreAllMocks());

  function captured(count: number | undefined): string {
    const out = vi.spyOn(process.stdout, "write").mockImplementation(() => true);
    const err = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    printUnpricedNote(count);
    return [...out.mock.calls, ...err.mock.calls].map((c) => String(c[0])).join("");
  }

  it("names a positive count", () => {
    expect(captured(3)).toContain("3 observation(s) had no rate");
  });

  it.each([0, -1, undefined])("prints nothing for %s", (count) => {
    expect(captured(count)).toBe("");
  });
});
