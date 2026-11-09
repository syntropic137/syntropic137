import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    environment: "node",
    // Unsets the CLI's own env vars and gives each test file its own
    // SYN_CONFIG_DIR, before the file imports anything.
    setupFiles: ["tests/setup-env.ts"],
  },
});
