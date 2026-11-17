import { describe, expect, it } from "vitest";
import { claimConfigDir } from "./claim.js";

// Paired with file-b.test.ts (#2223).
describe("per-file SYN_CONFIG_DIR", () => {
  it("is not shared with any other test file", () => {
    expect(claimConfigDir("file-a")).toEqual(["file-a.claim"]);
  });
});
