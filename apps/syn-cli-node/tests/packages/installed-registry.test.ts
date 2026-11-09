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

/**
 * A registry written before #883 can already hold two records for one
 * package; dedup on write never touches it (issue #886).
 */
describe("loadInstalled with duplicate records", () => {
  function stored(version: string, installedAt: string, ids: string[]) {
    return {
      package_name: "code-review",
      package_version: version,
      source: `org/code-review@${version}`,
      source_ref: `v${version}`,
      installed_at: installedAt,
      format: "single",
      workflows: ids.map((id) => ({ id, name: id })),
      marketplace_source: `marketplace-${version}`,
      git_sha: `sha-${version}`,
    };
  }

  it("merges them into the newest record, carrying every workflow id", () => {
    saveInstalled({
      version: 1,
      installations: [
        stored("0.4.0", "2026-10-02T00:00:00.000Z", ["shared", "only-new"]),
        stored("0.3.0", "2026-10-01T00:00:00.000Z", ["shared", "only-old"]),
      ],
    });

    const { installations } = loadInstalled();
    expect(installations).toHaveLength(1);
    expect(installations[0]).toEqual({
      ...stored("0.4.0", "2026-10-02T00:00:00.000Z", ["shared", "only-new"]),
      workflows: [
        { id: "shared", name: "shared" },
        { id: "only-new", name: "only-new" },
        { id: "only-old", name: "only-old" },
      ],
    });
  });

  // One record can already repeat an id: two YAML files declaring the same
  // workflow resolve to two refs, and recordInstallation stores both.
  for (const repeatIn of ["newer", "older"] as const) {
    it(`admits each id once when the ${repeatIn} record repeats one`, () => {
      const repeated = ["repeated", "repeated"];
      const newer = stored("0.4.0", "2026-10-02T00:00:00.000Z", repeatIn === "newer" ? repeated : ["unique"]);
      const older = stored("0.3.0", "2026-10-01T00:00:00.000Z", repeatIn === "older" ? repeated : ["unique"]);
      saveInstalled({ version: 1, installations: [older, newer] });

      const ids = loadInstalled().installations[0]?.workflows.map((w) => w.id);
      expect([...(ids ?? [])].sort()).toEqual(["repeated", "unique"]);
    });
  }

  it("returns a registry without duplicates unchanged", () => {
    const registry = {
      version: 1,
      installations: [
        stored("0.3.0", "2026-10-01T00:00:00.000Z", ["a"]),
        { ...stored("1.0.0", "2026-09-01T00:00:00.000Z", ["b"]), package_name: "sdlc-trunk" },
      ],
    };
    saveInstalled(registry);

    expect(loadInstalled()).toEqual(registry);
  });
});
