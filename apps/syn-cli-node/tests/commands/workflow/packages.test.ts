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

  describe("unsupported URL schemes (issue #1118)", () => {
    // `syn workflow packages` used to answer "is this source remote?" with
    // its own `src.includes("://")`, while resolver.ts's parseSource - the
    // function `install` and `update` actually resolve a source with -
    // answers it with a fixed list of four prefixes. Every scheme outside
    // that list was therefore remote to the listing and local to the parser,
    // so the row was never liveness-checked and never pruned. These pin the
    // whole class, not just the `file://` example from the issue: any
    // scheme parseSource does not recognise is a source install could never
    // have cloned, so a dead row must not survive on the strength of its
    // colon-slash-slash.
    const unsupported: readonly [string, string][] = [
      ["file-url-pkg", "file:///definitely/missing/syn1118"],
      ["ftp-url-pkg", "ftp://example.com/missing-syn1118"],
      ["s3-url-pkg", "s3://bucket/missing-syn1118"],
      ["git-url-pkg", "git://example.com/missing-syn1118.git"],
    ];

    for (const [pkg, source] of unsupported) {
      it(`prunes a dead ${source.split(":")[0]}:// source`, async () => {
        install(pkg, source);
        await packagesCommand.handler({ positionals: [], values: {} });

        const out = stdout();
        expect(out).not.toContain(pkg);
        expect(out).toContain("No packages installed yet.");
      });
    }

    it("prunes a dead local path that merely contains :// somewhere in it", async () => {
      // The old predicate looked for `://` ANYWHERE, not as a prefix, so an
      // absolute path that happens to contain those three characters was
      // classified remote and exempted from the existence check. parseSource
      // reads it for what it is: a path starting with `/`.
      install("colon-path-pkg", "/tmp/syn1118-gone/weird://name");
      await packagesCommand.handler({ positionals: [], values: {} });

      const out = stdout();
      expect(out).not.toContain("colon-path-pkg");
      expect(out).toContain("No packages installed yet.");
    });

    // Guards the other direction: routing the question through parseSource
    // must not start pruning sources that really are remote and really are
    // still installable. These pass before and after the change - they are
    // here so a future "simplification" of the filter cannot quietly delete
    // the remote cases along with the divergence.
    const stillListed: readonly [string, string][] = [
      ["https-pkg", "https://github.com/acme/widgets.git"],
      ["http-pkg", "http://example.com/widgets.git"],
      ["scp-pkg", "git@github.com:acme/widgets.git"],
      ["ssh-pkg", "ssh://git@github.com/acme/widgets.git"],
      ["bare-pkg", "some-marketplace-plugin-syn1118"],
    ];

    for (const [pkg, source] of stillListed) {
      it(`keeps ${source}, which has no local path to be missing`, async () => {
        install(pkg, source);
        await packagesCommand.handler({ positionals: [], values: {} });

        expect(stdout()).toContain(pkg);
      });
    }
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
