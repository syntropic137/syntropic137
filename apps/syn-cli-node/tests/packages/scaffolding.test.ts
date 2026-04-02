import { describe, it, expect, afterEach } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { scaffoldSinglePackage, scaffoldMultiPackage, detectFormat } from "../../src/packages/resolver.js";

function makeTmpDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), "syn-test-scaffold-"));
}

function cleanup(dir: string): void {
  fs.rmSync(dir, { recursive: true, force: true });
}

describe("scaffoldSinglePackage", () => {
  let tmpDir: string;

  afterEach(() => {
    if (tmpDir) cleanup(tmpDir);
  });

  it("creates workflow.yaml and phase files", () => {
    tmpDir = path.join(makeTmpDir(), "test-wf");
    scaffoldSinglePackage(tmpDir, { name: "Test Workflow", workflowType: "research", numPhases: 2 });

    expect(fs.existsSync(path.join(tmpDir, "workflow.yaml"))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, "README.md"))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, "phases"))).toBe(true);

    const phaseFiles = fs.readdirSync(path.join(tmpDir, "phases"));
    expect(phaseFiles.length).toBe(2);

    expect(detectFormat(tmpDir)).toBe("single");
  });
});

describe("scaffoldMultiPackage", () => {
  let tmpDir: string;

  afterEach(() => {
    if (tmpDir) cleanup(tmpDir);
  });

  it("creates plugin manifest and workflows dir", () => {
    tmpDir = path.join(makeTmpDir(), "test-plugin");
    scaffoldMultiPackage(tmpDir, { name: "Test Plugin", workflowType: "research", numPhases: 2 });

    expect(fs.existsSync(path.join(tmpDir, "syntropic137-plugin.json"))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, "workflows"))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, "README.md"))).toBe(true);

    expect(detectFormat(tmpDir)).toBe("multi");
  });
});
