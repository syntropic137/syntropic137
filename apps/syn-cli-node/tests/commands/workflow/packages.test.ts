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
});
