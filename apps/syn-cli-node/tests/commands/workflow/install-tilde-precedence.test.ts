/**
 * Regression test for issue #1045's second review round: `isBarePluginName`
 * used to treat `~` as a bare plugin name (no file literally named `~`
 * exists), so `installCommand.handler` tried marketplace resolution BEFORE
 * `resolveSource`/`parseSource` ever got a chance to expand it to the home
 * directory. A marketplace entry literally named `~` would have won.
 *
 * `parseSource('~')` was already covered directly in
 * `tests/packages/resolver.test.ts`, but that only proves the helper is
 * correct - it says nothing about which helper `installCommand.handler`
 * reaches for FIRST. This test exercises the handler itself, with
 * marketplace resolution mocked, and asserts it is never called for `~`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

vi.mock("../../../src/marketplace/client.js", () => ({
  resolveFromMarketplace: vi.fn(),
}));

import { installCommand } from "../../../src/commands/workflow/install.js";
import { resolveFromMarketplace } from "../../../src/marketplace/client.js";

describe("installCommand handler: tilde precedence (issue #1045)", () => {
  let fakeHome: string;

  beforeEach(() => {
    // A controlled, empty "home directory" so resolveSource's eventual
    // detectFormat() call fails deterministically (no yaml files present)
    // regardless of what the real sandbox home directory happens to
    // contain - the assertion under test is about ORDER, not outcome.
    fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "syn-tilde-test-"));
    vi.spyOn(os, "homedir").mockReturnValue(fakeHome);
    vi.spyOn(process.stdout, "write").mockReturnValue(true);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    fs.rmSync(fakeHome, { recursive: true, force: true });
  });

  it("never tries marketplace resolution for '~' - it must expand to the home directory instead", async () => {
    await expect(
      installCommand.handler({ positionals: ["~"], values: {} }),
    ).rejects.toThrow();

    expect(resolveFromMarketplace).not.toHaveBeenCalled();
  });

  it("never tries marketplace resolution for '~/pkg' either", async () => {
    await expect(
      installCommand.handler({ positionals: ["~/pkg"], values: {} }),
    ).rejects.toThrow();

    expect(resolveFromMarketplace).not.toHaveBeenCalled();
  });

  it("still tries marketplace resolution for an actual bare plugin name", async () => {
    vi.mocked(resolveFromMarketplace).mockResolvedValue(null);

    await expect(
      installCommand.handler({ positionals: ["some-plugin"], values: {} }),
    ).rejects.toThrow();

    expect(resolveFromMarketplace).toHaveBeenCalledWith("some-plugin", "main");
  });
});
