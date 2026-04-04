import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CLIError } from "../../../src/framework/errors.js";

// Mock the marketplace client before importing the commands so
// search.ts captures these mocked exports instead of the real
// marketplace/client module.
vi.mock("../../../src/marketplace/client.js", () => ({
  searchAllRegistries: vi.fn(),
  resolvePluginByName: vi.fn(),
}));

import { searchCommand, infoCommand } from "../../../src/commands/workflow/search.js";
import { searchAllRegistries, resolvePluginByName } from "../../../src/marketplace/client.js";

describe("workflow search commands", () => {
  beforeEach(() => {
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

  describe("search", () => {
    it("renders search results table", async () => {
      vi.mocked(searchAllRegistries).mockResolvedValue([
        [
          "community",
          {
            name: "code-review",
            version: "1.0.0",
            description: "Automated code review workflow",
            category: "review",
            tags: ["review", "quality"],
            source: "workflows/code-review",
          },
        ],
      ]);

      await searchCommand.handler({
        positionals: ["review"],
        values: {},
      });

      const out = stdout();
      expect(out).toContain("code-review");
      expect(out).toContain("1.0.0");
      expect(out).toContain("review");
      expect(out).toContain("Available Workflows");
    });

    it("shows empty message when no results", async () => {
      vi.mocked(searchAllRegistries).mockResolvedValue([]);

      await searchCommand.handler({
        positionals: ["nonexistent"],
        values: {},
      });

      expect(stdout()).toContain("No workflows found");
    });
  });

  describe("info", () => {
    it("renders plugin details", async () => {
      vi.mocked(resolvePluginByName).mockResolvedValue([
        "community",
        { repo: "syntropic137/workflow-library", path: "workflows" },
        {
          name: "deploy-pipeline",
          version: "2.1.0",
          description: "Multi-phase deployment workflow",
          category: "deployment",
          tags: ["deploy", "ci-cd"],
          source: "workflows/deploy-pipeline",
        },
      ]);

      await infoCommand.handler({
        positionals: ["deploy-pipeline"],
        values: {},
      });

      const out = stdout();
      expect(out).toContain("deploy-pipeline");
      expect(out).toContain("2.1.0");
      expect(out).toContain("Multi-phase deployment workflow");
      expect(out).toContain("deploy, ci-cd");
      expect(out).toContain("community");
    });

    it("throws CLIError when plugin not found", async () => {
      vi.mocked(resolvePluginByName).mockResolvedValue(null);

      await expect(
        infoCommand.handler({
          positionals: ["nonexistent"],
          values: {},
        }),
      ).rejects.toThrow(CLIError);
    });

    it("throws CLIError when name is missing", async () => {
      await expect(
        infoCommand.handler({ positionals: [], values: {} }),
      ).rejects.toThrow(CLIError);
    });
  });
});
