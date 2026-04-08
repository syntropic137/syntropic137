import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { exportCommand } from "../../../src/commands/workflow/export.js";
import { CLIError } from "../../../src/framework/errors.js";

describe("workflow export command", () => {
  const mockFetch = vi.fn();
  let tmpDir: string;

  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
    vi.spyOn(process.stdout, "write").mockReturnValue(true);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "syn-test-export-"));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  function jsonResponse(data: unknown, status = 200): Response {
    return new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  function stdout(): string {
    return (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls
      .map((c: unknown[]) => String(c[0]))
      .join("");
  }

  it("exports into an empty directory", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        workflow_name: "Code Review",
        files: {
          "workflow.yaml": "name: Code Review\n",
          "phases/phase-1.md": "## Phase 1\n",
        },
      }),
    );

    await exportCommand.handler({
      positionals: ["wf-123"],
      values: { format: "package", output: tmpDir },
    });

    const out = stdout();
    expect(out).toContain("Export Complete");
    expect(out).toContain("Code Review");
    expect(fs.existsSync(path.join(tmpDir, "workflow.yaml"))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, "phases", "phase-1.md"))).toBe(true);
  });

  it("exports into a non-empty directory when no files collide", async () => {
    fs.writeFileSync(path.join(tmpDir, "existing-file.txt"), "existing content");

    mockFetch.mockResolvedValue(
      jsonResponse({
        workflow_name: "Code Review",
        files: { "workflow.yaml": "name: Code Review\n" },
      }),
    );

    await expect(
      exportCommand.handler({
        positionals: ["wf-123"],
        values: { format: "package", output: tmpDir },
      }),
    ).resolves.not.toThrow();

    expect(fs.existsSync(path.join(tmpDir, "workflow.yaml"))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, "existing-file.txt"))).toBe(true);
  });

  it("fails when an export file would overwrite an existing file", async () => {
    fs.writeFileSync(path.join(tmpDir, "workflow.yaml"), "old content");

    mockFetch.mockResolvedValue(
      jsonResponse({
        workflow_name: "Code Review",
        files: { "workflow.yaml": "name: Code Review\n" },
      }),
    );

    await expect(
      exportCommand.handler({
        positionals: ["wf-123"],
        values: { format: "package", output: tmpDir },
      }),
    ).rejects.toThrow(CLIError);

    // Original file is untouched
    expect(fs.readFileSync(path.join(tmpDir, "workflow.yaml"), "utf-8")).toBe("old content");
  });

  it("overwrites existing files with --force", async () => {
    fs.writeFileSync(path.join(tmpDir, "workflow.yaml"), "old content");

    mockFetch.mockResolvedValue(
      jsonResponse({
        workflow_name: "Code Review",
        files: { "workflow.yaml": "name: Code Review\n" },
      }),
    );

    await expect(
      exportCommand.handler({
        positionals: ["wf-123"],
        values: { format: "package", output: tmpDir, force: true },
      }),
    ).resolves.not.toThrow();

    expect(fs.readFileSync(path.join(tmpDir, "workflow.yaml"), "utf-8")).toBe("name: Code Review\n");
  });

  it("rejects unsafe path traversal in export manifest", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        workflow_name: "Malicious",
        files: { "../../../etc/evil": "bad content" },
      }),
    );

    await expect(
      exportCommand.handler({
        positionals: ["wf-bad"],
        values: { format: "package", output: tmpDir },
      }),
    ).rejects.toThrow(CLIError);
  });

  it("throws CLIError when workflow-id is missing", async () => {
    await expect(
      exportCommand.handler({ positionals: [], values: {} }),
    ).rejects.toThrow(CLIError);
  });

  it("throws CLIError for invalid format", async () => {
    await expect(
      exportCommand.handler({
        positionals: ["wf-123"],
        values: { format: "zip" },
      }),
    ).rejects.toThrow(CLIError);
  });
});
