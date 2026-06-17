import { defineConfig } from "vitest/config";
import os from "node:os";
import path from "node:path";

// WHY: many CLI modules read SYN_CONFIG_DIR at import time
// (persistence/store.ts captures it into a module-level const). Setting it
// here forces tests to write into an isolated tmp tree instead of the
// developer's real ~/.syntropic137/ directory.
const SYN_TEST_CONFIG_DIR = path.join(
  os.tmpdir(),
  `syn-cli-vitest-${process.pid}`,
);

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    environment: "node",
    env: {
      SYN_CONFIG_DIR: SYN_TEST_CONFIG_DIR,
    },
  },
});
