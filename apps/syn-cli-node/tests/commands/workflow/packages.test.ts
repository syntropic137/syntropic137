/**
 * `syn workflow packages` used to classify a source as remote (and so always
 * show it, even once the on-disk package is long gone) using its own inline
 * shorthand regex - one that allowed a `#fragment` suffix nothing in this
 * codebase ever produces, and that could disagree with resolver.ts's
 * `isGitHubShorthand`, the parser actually used to resolve a source. This
 * asserts the two are unified: a source shaped like `org/repo#v1` is not a
 * valid GitHub repo identity (issue #1045/#1066 review) and, since no local
 * path by that name exists either, must be pruned from the listing rather
 * than kept around by a looser, second classifier.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { packagesCommand } from "../../../src/commands/workflow/install.js";
import { recordInstallation, saveInstalled } from "../../../src/packages/resolver.js";

function install(packageName: string, source: string) {
  recordInstallation({
    packageName,
    packageVersion: "1.0.0",
    source,
    sourceRef: "main",
    format: "single",
    workflows: [{ id: `${packageName}-wf`, name: packageName }],
  });
}

describe("workflow packages", () => {
  beforeEach(() => {
    saveInstalled({ version: 1, installations: [] });
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

  it("keeps a genuine GitHub shorthand source even though the local path is gone", async () => {
    install("good-pkg", "acme/widgets");
    await packagesCommand.handler({ positionals: [], values: {} });
    expect(stdout()).toContain("good-pkg");
  });

  it("prunes a #fragment-suffixed source: not a valid repo identity and no local path exists", async () => {
    install("frag-pkg", "acme/widgets#v1");
    await packagesCommand.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).not.toContain("frag-pkg");
    expect(out).toContain("No packages installed yet.");
  });

  describe("home-relative sources (issue #1066)", () => {
    // `~/pkg` only means something once it is expanded against a home
    // directory - the real $HOME the test happens to run under is not a
    // fixture we control, so pin os.homedir() the same way
    // install-tilde-precedence.test.ts does, and use a directory name that
    // could never coincidentally already exist there.
    let fakeHome: string;

    beforeEach(() => {
      fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "syn-packages-tilde-test-"));
      vi.spyOn(os, "homedir").mockReturnValue(fakeHome);
    });

    afterEach(() => {
      fs.rmSync(fakeHome, { recursive: true, force: true });
    });

    it("lists a package installed from a home-relative path whose directory genuinely exists", async () => {
      const pkgDir = path.join(fakeHome, "tilde-pkg-1066");
      fs.mkdirSync(pkgDir);

      install("tilde-pkg-1066", "~/tilde-pkg-1066");
      await packagesCommand.handler({ positionals: [], values: {} });

      expect(stdout()).toContain("tilde-pkg-1066");
    });

    it("still prunes a home-relative source whose directory does not exist", async () => {
      // No directory created at `${fakeHome}/gone-pkg` - this is what
      // distinguishes a real liveness check from one that treats every `~`
      // source as always-live once it merely stops crashing on the prefix.
      install("gone-pkg", "~/gone-pkg");
      await packagesCommand.handler({ positionals: [], values: {} });

      const out = stdout();
      expect(out).not.toContain("gone-pkg");
      expect(out).toContain("No packages installed yet.");
    });
  });
});
