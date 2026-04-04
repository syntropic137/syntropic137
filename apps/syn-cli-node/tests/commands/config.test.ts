import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { configGroup } from "../../src/commands/config.js";
import { CLIError } from "../../src/framework/errors.js";

describe("config commands", () => {
  beforeEach(() => {
    vi.spyOn(process.stdout, "write").mockReturnValue(true);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  function stdout(): string {
    return (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls
      .map((c: unknown[]) => String(c[0]))
      .join("");
  }

  describe("show", () => {
    const handler = configGroup.getCommand("show")!.handler;

    it("displays configuration with defaults", async () => {
      delete process.env["SYN_API_URL"];
      delete process.env["SYN_API_TOKEN"];
      delete process.env["SYN_API_USER"];
      delete process.env["SYN_API_PASSWORD"];

      await handler({ positionals: [], values: {} });
      const out = stdout();
      expect(out).toContain("CLI Configuration");
      expect(out).toContain("API URL");
      expect(out).toContain("localhost:8137");
    });

    it("shows auth type when token is set", async () => {
      vi.stubEnv("SYN_API_TOKEN", "test-token-123");

      await handler({ positionals: [], values: {} });
      const out = stdout();
      expect(out).toContain("token");
      expect(out).toContain("set");
    });
  });

  describe("validate", () => {
    const handler = configGroup.getCommand("validate")!.handler;

    it("passes for localhost with no auth", async () => {
      delete process.env["SYN_API_URL"];
      delete process.env["SYN_API_TOKEN"];
      delete process.env["SYN_API_USER"];
      delete process.env["SYN_API_PASSWORD"];

      await handler({ positionals: [], values: {} });
      expect(stdout()).toContain("valid");
    });

    it("fails for remote URL without auth", async () => {
      vi.stubEnv("SYN_API_URL", "https://api.example.com");
      delete process.env["SYN_API_TOKEN"];
      delete process.env["SYN_API_USER"];
      delete process.env["SYN_API_PASSWORD"];

      await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    });

    it("passes for remote URL with token auth", async () => {
      vi.stubEnv("SYN_API_URL", "https://api.example.com");
      vi.stubEnv("SYN_API_TOKEN", "my-token");

      await handler({ positionals: [], values: {} });
      expect(stdout()).toContain("valid");
    });
  });

  describe("env", () => {
    const handler = configGroup.getCommand("env")!.handler;

    it("prints environment variable template", async () => {
      await handler({ positionals: [], values: {} });
      const out = stdout();
      expect(out).toContain("SYN_API_URL");
      expect(out).toContain("SYN_API_TOKEN");
      expect(out).toContain("export");
    });
  });
});
