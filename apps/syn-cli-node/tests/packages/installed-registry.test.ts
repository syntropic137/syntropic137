/**
 * One installation record per package (issue #822).
 *
 * `recordInstallation` used to append unconditionally. That only worked
 * because `update` called `removeInstallation` first, and because a second
 * `install` of the same package failed server-side before ever reaching this
 * code. Install is an upsert now, so appending would leave two records
 * pointing at the same workflow ids: `list` double-counts and `uninstall`
 * removes only one of them.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  loadInstalled,
  recordInstallation,
  saveInstalled,
} from "../../src/packages/resolver.js";

function record(version: string, workflowId = "code-review") {
  return {
    packageName: "code-review",
    packageVersion: version,
    source: "code-review",
    sourceRef: "main",
    format: "plugin" as const,
    workflows: [{ id: workflowId, name: "Code Review" }],
    marketplaceSource: null,
    gitSha: null,
  };
}

describe("recordInstallation", () => {
  beforeEach(() => {
    saveInstalled({ version: 1, installations: [] });
  });

  it("replaces the existing record for the same package", () => {
    recordInstallation(record("0.3.0"));
    recordInstallation(record("0.4.0"));

    const { installations } = loadInstalled();
    expect(installations).toHaveLength(1);
    expect(installations[0]!.package_version).toBe("0.4.0");
  });

  it("does not duplicate on a same-version reinstall", () => {
    recordInstallation(record("0.3.0"));
    recordInstallation(record("0.3.0"));

    expect(loadInstalled().installations).toHaveLength(1);
  });

  it("keeps records for other packages", () => {
    recordInstallation(record("0.3.0"));
    recordInstallation({ ...record("1.0.0"), packageName: "sdlc-trunk" });

    const names = loadInstalled().installations.map((i) => i.package_name);
    expect(names.sort()).toEqual(["code-review", "sdlc-trunk"]);
  });
});
